#!/usr/bin/env python3
"""The team dashboard: build each product's page data, publish it, and upload the page itself.

The dashboard is a Railway site (dashboard/server.ts), open to view while DASHBOARD_PUBLIC is on; publishing always
needs the token. Each product has one page; every publish is kept as a version, so the team can see what was live
or proposed in any week.

Usage:
  python dashboard.py publish --asin <ASIN> --run <run> --state applied|proposed [--label "Weekly run"]
                              [--date YYYY-MM-DD] [--by "Kim"] [--due-plan <plan.json>] [--dry-run]
  python dashboard.py lineup --asin <ASIN> [--by "Kim"] [--dry-run]
                           a product lined up for AI bidding but still on Scale Insights bid rules: its page is
                           built from data/asins/<ASIN>.json alone (registry.stage "queued"), no run folder
  python dashboard.py refresh --asin <ASIN> [--note "what changed"] [--run <run>]
                           republish a page from the product file (name, brief, open items, activity, last 30 days),
                           keeping the latest run's tables from the live page: for anyone's daily or weekly update,
                           without the run folder (runs/ is not in git). With --run (an AI-managed product's run
                           folder) the product file also remembers that run: its SQP totals are appended to
                           "sqp_history" when they are for a newer week than the newest entry (the last 26 are kept),
                           and "data_stage" becomes the run's stage, except that a recorded "mature" stays; the run's
                           For Growth gate counts (growth.json's candidates) are kept in "growth", as publish keeps them.
                           --dry-run prints what would be recorded and writes nothing
  python dashboard.py rank --asin <ASIN> --radar <run>/radar_p*.json [--days 30] [--top 12] [--dry-run]
                           organic rank on the product's main searches, from DataDive Rank Radar pages
                           (get_rank_radar_data): stored in the product file as "rank", then the page is refreshed
  python dashboard.py approvals --asin <ASIN> --run <run> [--live <list_resources file>] [--now <ISO UTC>] [--dry-run]
                              [--discard-unapplied]
                           the team's per-row approvals (GET /api/reviews/<ASIN>) on this run's Bids item become
                           <run>/payloads/approved/*.json (with rows.json, and payloads/approved_decisions.json naming
                           who approved each row), and each decline is stored as a lock in the product file's
                           "decisions" (an approval locks its row only once it has gone out: see applied). It only reads
                           the dashboard and writes local files: it never writes to Amazon. An approval counts only
                           when it says what the person saw (`seen`) and that matches the row in plan.json, and only
                           from a signer at the row's approval_required level (Kim, then Lee, then anyone who
                           signed). A bid the auto lane would cap is written at the cap (shadow runs). --live (MAP
                           list_resources rows for the keywords and targets) leaves out rows whose bid or state moved
                           since the plan. Rows listed in <run>/payloads/applied_rows.json are not emitted again.
                           It refuses, writing nothing, while payloads/approved/ holds rows applied_rows.json doesn't
                           record (run applied first; --discard-unapplied only when they did not go out). Calendar dates
                           never defer an audit. --dry-run and decisions-only mode remain non-executing. Prints a JSON summary.
  python dashboard.py reviews --asin <ASIN> --save <run>/reviews.json
                           before planning a run: save the team's decisions (GET /api/reviews/<ASIN>, as it comes) in
                           the run folder, as {asin, saved_at, entries}; plan.py turns every decline in it into a lock,
                           and refuses to plan without it whenever the product file holds a bids item, or with one for
                           another ASIN or saved more than a day before the run. It also saves Growth's "Picked up" and
                           "Copy pushed" clicks (GET /api/items/<ASIN>) beside it as item_statuses.json, which publish
                           moves onto the For Growth item (a dashboard without that route: a warning, the decisions are
                           still saved). It only reads the dashboard.
  python dashboard.py growth --asin <ASIN> --anchor [--clicks-daily <run>/clicks_daily.json]
                             [--date YYYY-MM-DD --source hand] [--dry-run]
                           the For Growth anchor (the later of the Monday launch date and the first ad click; a date set
                           by hand wins and stays) and the next listing pass window, into the product file's growth block
                           (growth.anchor, growth.next_pass); prints both. The onboarding runbook's anchor step.
  python dashboard.py growth --asin <ASIN> --enable|--disable [--by "Kim"] [--dry-run]
                           turn the For Growth listing passes on or off for one product (growth.enabled; Kim or
                           Lee, in Kim's rollout order), with an activity line
  python dashboard.py growth --asin <ASIN> --run <run> --emit [--by "Lee"] [--dry-run]
                           a fresh For Growth block by hand (trigger manual), any day: built from the run's plan.json and
                           listing.json, stamped with the time of the emit (SGT), written to <run>/growth.json and merged
                           into the product file's For Growth item (an open item keeps its status). Never publishes: run
                           refresh or publish to show it. --dry-run prints the block and writes nothing.
  python dashboard.py applied --asin <ASIN> --run <run> --folder auto|review|approved [--date YYYY-MM-DD] [--dry-run]
                              [--now <ISO UTC>] [--rows <row_id,...>] [--record-anyway]
                           right after a payload folder went out: its rows (the folder's rows.json) are added to
                           <run>/payloads/applied_rows.json with the day and the folder, and each row from approved/ gets
                           an approve lock in the product file's "decisions" (auto/ and review/ rows get none, except a
                           creation: from any folder it gets a create lock, kind "create", so it is never made again). Never
                           payloads/held/. For every folder it first refuses a creation whose search another `applied`
                           recorded as created (rows this run already recorded are exempt); with --folder review it also
                           reads the dashboard and refuses while the run's bids item has any decision, or a row of
                           review/ was declined after the plan. Run it with --dry-run BEFORE applying any folder, approved/
                           included: that is the check, valid any day (--now for deterministic tests). --record-anyway records a folder that
                           already went out. Run it for real only after the MAP apply went through: it can't tell whether
                           a folder went out, and records whatever the folder's rows.json names, or only the rows --rows
                           names when only part of the folder went out (read back); the rest stays unrecorded. It never
                           writes to Amazon.
  python dashboard.py claim --asin <ASIN> --what "Weekly run" [--until YYYY-MM-DD] [--force]
                                           tell the team you are working on a product (one person per product)
  python dashboard.py release --asin <ASIN> [--note "what was done"]
  python dashboard.py note --text "..." [--asin <ASIN>]      a line in the team's activity feed
  python dashboard.py team [--asin <ASIN>]                   who is working on what, and recent activity
  python dashboard.py site                 upload dashboard/site/* (after changing the page)
  python dashboard.py list                 what the dashboard holds now, and whether your product files are in sync
  python dashboard.py login [--email you@x] [--label "Sam's laptop"]
                           sign this laptop in with your dashboard account. Type it yourself in a terminal: it asks for
                           your password (hidden). The dashboard's laptop key is saved as PUBLISH_TOKEN in the secrets
                           file; publish, claim, reviews and the rest then run under your name. Lasts a year; an admin
                           ends it on the Users page. An AI agent never runs this for anyone.
  python dashboard.py logout               end this laptop's key and remove it from the secrets file
  python dashboard.py users list           the dashboard's accounts (admins)
  python dashboard.py users add --email <email> --name <Name> --role admin|ppc|growth
                           add an account; prints its temporary password once. The very first one (an admin) can be
                           added with an old personal key; after that only an admin adds people.
  (The commands below make the old keys. They keep working until the Railway variable LEGACY_KEYS is "off".)
  python dashboard.py secrets --init       run owner: create the local secrets file; prints only SHA-256 hashes
  python dashboard.py secrets --personal "Name"   teammate: create your own publish token; prints its hash
  python dashboard.py secrets --personal "Name" --role growth
                           Kim or Lee: a For Growth key for a Growth member (it only sets "Picked up" and "Copy
                           pushed"), saved with ROLE=growth in its own file beside the secrets file (growth-<name>.env),
                           never printed; prints the GROWTH_PUBLISHERS entry (Name:<sha256>). Kim and Lee are
                           approver names and are refused.
  python dashboard.py secrets --hashes     print the hashes again (for the Railway variables)

When to publish:
  - after the preview is built: --state proposed (the page shows "Waiting for approval");
  - after the apply is verified and log_invest.py has run: --state applied. Only the rows <run>/payloads/applied_rows.json
    (dashboard.py applied) records read applied; the rest say why not (declined, from a <run>/reviews.json saved after
    the decisions; held; not applied; waiting for a person). A run planned with the lanes and no applied_rows.json went
    out with nothing; only an older run without one reads every row applied.

The doc is built from config.json, data/asins/<ASIN>.json (registry, brief, open_items, activity, reviews,
baseline, invest_log, harvest, monitor) and the run folder: plan.json, plus applied.json when the apply deviated from
the plan (see references/dashboard.md; not payloads/applied_rows.json, which records the rows that went out). --due-plan adds a "fix due next run" column from a later plan.json.
For Growth (docs/superpowers/specs/2026-10-22-for-growth-tab-design.md): publish also keeps the run's evidence-gate counts
(growth.json's candidates, and its anchor when the product file has none), moves Growth's saved clicks
(item_statuses.json) onto the For Growth item, and resolves a picked-up item when the run's listing.json shows the copy
changed (a resolved pass: the next window, the quiet clock). The card carries growth = {enabled, anchor, next_pass}.
The monitor block (last 30 days from Scale Insights get_sales_data) is written into the product file before publishing.

Teammates: every publish sends the page version your product file last saw (its "dashboard" block). If someone else
published the page since, the server refuses (HTTP 409) and nothing is overwritten: git pull, then publish again.
After a publish the new version is written into the product file, so commit and push it. --force skips the check.

Secrets: the publish token comes from the PPC_DASHBOARD_TOKEN environment variable, or PUBLISH_TOKEN in the secrets
file (PPC_DASHBOARD_SECRETS, default ~/.config/your-ppc-repo-dashboard/secrets.env). They never go in this skill's
folder: it is committed to the your-ppc-repo repo and shared. This script never prints a secret.
"""
import argparse
import copy
import datetime as dt
import glob
import gzip
import hashlib
import json
import math
import os
import re
import secrets as pysecrets
import sys
import urllib.error
import urllib.request
from human_review import (ACTIVE as ACTIVE_STATUSES, LEVELS, _set_status, attach as attach_human_review, card_money,
                          merge as merge_human_review, signer_level, transition as transition_human_review, sgt_today,
                          validate as validate_human_review)
import daypart_base
import growth
import lanes
import listing_size
import plan_lanes
import ownership_scope
from placement_review import rank_tos
from plan import (as_written, load_clicks_daily, load_listing, payload_files, payload_row_ids,
                  dimension_pairs, own_sizes, product_sizes, write_json as write_payload_json)
from searchtext import norm

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SITE_DIR = os.path.join(SKILL, 'dashboard', 'site')
SITE_FILES = ['index.html', 'app.css', 'app.js', 'favicon.svg']
SECRETS_FILE = os.path.expanduser(os.environ.get('PPC_DASHBOARD_SECRETS', '~/.config/your-ppc-repo-dashboard/secrets.env'))
sys.path.insert(0, HERE)
from preview import RULES  # noqa: E402

TEAM_FIELDS = ('invest', 'new_campaigns', 'reused_campaigns', 'pauses', 'bid_changes', 'bids_up', 'bids_down', 'budgets',
               'negatives', 'negatives_skipped', 'invest_now_day', 'invest_plan_day', 'invest_budget_day',
               'invest_orders_month', 'invest_net_month', 'window')
CHANGE_KEYS = ('step', 'type', 'keyword', 'item', 'match', 'role', 'family', 'campaign', 'ad_group', 'current', 'new',
               'change', 'tos', 'tos_bid', 'tos_now', 'budget', 'budget_now', 'sug_low', 'sug_median', 'sug_high', 'bid_source',
               'source', 'evidence', 'why', 'how', 'clicks90', 'orders90', 'spend90', 'cvr', 'breakeven',
               'campaign_id', 'ad_group_id', 'keyword_id', 'status', 'note', 'owner_kind')
TEXT_KEYS = ('why', 'how', 'evidence', 'note')
TERM_COLS = ['term', 'verdict', 'why', 'sqp_volume', 'index', 'index_basis', 'market_cvr', 'sqp_our_clicks',
             'sqp_our_purchases', 'ad_clicks', 'ad_orders', 'ad_spend', 'impression_share', 'be_cpc']
# The home card carries this much of the product file's monitor block (last 30 days, Scale Insights get_sales_data).
MONITOR_CARD = ('start', 'end', 'sales', 'orders', 'ad_spend', 'acos', 'breakeven_acos', 'tacos', 'organic_share', 'profit')


class Texts:
    """Repeated strings (reasons, evidence) are stored once; rows point at them by index."""
    def __init__(self):
        self.list, self.ix = [], {}

    def __call__(self, s):
        if s is None or s == '':
            return None
        s = str(s)
        if s not in self.ix:
            self.ix[s] = len(self.list)
            self.list.append(s)
        return self.ix[s]


def rnd(v):
    return round(v, 4) if isinstance(v, float) else v


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def config():
    return load_json(os.path.join(SKILL, 'config.json'))


def data_dir(cfg, override=None):
    return override or cfg.get('data_dir') or os.path.join(SKILL, 'data')


def shorten(text, n=72):
    """A label for the dashboard's date lists: the text itself, or its first n characters on a word boundary."""
    text = str(text)
    return text if len(text) <= n else text[:n].rsplit(' ', 1)[0].rstrip(',;:') + '…'


def add_days(d, n):
    return (dt.date.fromisoformat(d) + dt.timedelta(days=n)).isoformat()


def monitor_card(a):
    m = a.get('monitor') or {}
    out = {k: rnd(m.get(k)) for k in MONITOR_CARD if m.get(k) is not None}
    prior = m.get('prior') or {}
    if prior.get('organic_share') is not None:
        out['prior'] = dict(start=prior.get('start'), end=prior.get('end'), organic_share=rnd(prior['organic_share']))
    return out or None


# ---- organic rank (DataDive Rank Radar) --------------------------------------------------------------------

NOT_RANKED = 101  # Rank Radar's value for "not in the top 100 results that day"


def read_pages(paths):
    """Rank Radar pages, saved either as plain JSON or as the tool-result wrapper Claude Code writes big outputs in."""
    rows = []
    for path in paths:
        with open(path, encoding='utf-8') as f:
            raw = f.read().strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = json.loads(raw[raw.index('{'):raw.rindex('}') + 1])
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and 'text' in obj[0]:
            obj = json.loads(obj[0]['text'])
        rows += obj.get('data') or []
    return rows


def rank_block(a, rows, days, top, pulled_at):
    """The product's main searches with their daily organic rank: the invest and prove-first searches first (they
    are what the AI pays to re-rank), then the radar's biggest relevant searches, up to `top`."""
    dates = sorted({r['date'][:10] for k in rows for r in (k.get('ranks') or []) if r.get('date')})
    end = dates[-1] if dates else None
    start = add_days(end, -(days - 1)) if end else None
    span = [add_days(start, i) for i in range(days)] if end else []
    inv = a.get('invest_log') or {}
    by_kw = {}
    for k in rows:
        kw = (k.get('keyword') or '').strip().lower()
        if kw and kw not in by_kw:
            by_kw[kw] = k
    picked = [kw for kw in inv if kw in by_kw]
    rest = sorted((kw for kw in by_kw if kw not in inv), key=lambda kw: -((by_kw[kw].get('searchVolume') or 0) * (by_kw[kw].get('relevancy') or 0.5)))
    picked += [kw for kw in rest if (by_kw[kw].get('relevancy') or 0) >= 0.5][:max(0, top - len(picked))]
    owner_since = (a.get('registry') or {}).get('owner_since')

    def at_or_before(org, i):
        for j in range(i, -1, -1):
            if org[j] is not None:
                return org[j]
        return None

    out = []
    for kw in picked:
        k = by_kw[kw]
        daily = {r['date'][:10]: r.get('organicRank') for r in (k.get('ranks') or []) if r.get('date')}
        org = [daily.get(d) for d in span]
        last = max((i for i, v in enumerate(org) if v is not None), default=None)
        now = org[last] if last is not None else None
        wk = at_or_before(org, last - 7) if last is not None and last >= 7 else None
        first = next((v for v in org if v is not None), None)
        base = None
        if owner_since and span and owner_since > span[0]:
            i = span.index(owner_since) - 1 if owner_since in span else len(span) - 1
            base = at_or_before(org, i)
        seen = [v for v in org if v is not None and v < NOT_RANKED]
        role = (inv.get(kw) or {}).get('role')
        out.append(dict(kw=kw, sv=k.get('searchVolume'), role=role, since=(inv.get(kw) or {}).get('since'),
                        org=org, now=now, week=wk, first=first, base=base, best=min(seen) if seen else None))
    # invest searches first; within each group, searches with a reading by rank, then the rest by search volume
    out.sort(key=lambda x: (x['role'] is None, x['now'] is None, x['now'] if x['now'] is not None else 0, -(x['sv'] or 0)))
    tracked = [x for x in out if x['now'] is not None]

    def moved(x, ref):
        if x['now'] is None or x[ref] is None:
            return None
        return x[ref] - x['now']  # positive = moved up the page

    summ = dict(searches=len(out), with_data=len(tracked),
                top10=sum(1 for x in tracked if x['now'] <= 10), top50=sum(1 for x in tracked if x['now'] <= 50),
                up7=sum(1 for x in out if (moved(x, 'week') or 0) > 0), down7=sum(1 for x in out if (moved(x, 'week') or 0) < 0),
                flat7=sum(1 for x in out if moved(x, 'week') == 0))
    missing = [kw for kw in inv if kw not in by_kw]
    return dict(source='DataDive Rank Radar', radar_id=a.get('rank_radar_id'), pulled_at=pulled_at, start=start, end=end,
                days=days, dates_with_data=len([d for d in dates if start and d >= start]), owner_since=owner_since,
                radar_started=a.get('rank_radar_since'), not_tracked=missing, keywords=out, summary=summ)


def rank_card(a):
    """The rank line on the product's card: yesterday's top-10 count and the 7-day movement."""
    r = a.get('rank')
    if not r:
        return dict(radar=bool(a.get('rank_radar_id')), started=a.get('rank_radar_since')) if a.get('rank_radar_id') else None
    return dict(radar=True, end=r.get('end'), started=r.get('radar_started'), **(r.get('summary') or {}))


def identity(cfg, a):
    """What the product is, for the cards and the page: its name, home-page group, thumbnail, Amazon title, launch
    date, and the 50/50 goal it is measured against (config.json goal)."""
    types = cfg.get('product_types') or []
    t = next(((i, x) for i, x in enumerate(types) if x['id'] == a.get('type')), None)
    out = dict(name=a.get('name') or a.get('product'), type=t[1]['id'] if t else 'other', type_label=t[1]['label'] if t else 'Other',
               type_note=t[1].get('note') if t else None, type_order=t[0] if t else len(types), image=a.get('image'), amazon_title=a.get('amazon_title'),
               launch_date=a.get('launch_date'), launch_source=a.get('launch_source'),
               goal={k: v for k, v in (cfg.get('goal') or {}).items() if not k.startswith('_')} or None)
    return {k: v for k, v in out.items() if v is not None}


def dated(a, next_run, next_label):
    """The product's open items, scheduled reviews and the next run, as the card's 'Coming up' list (first 5)."""
    today = dt.date.today().isoformat()
    items = a.get('open_items') or []
    reviews = list(a.get('reviews') or [])
    future_reviews = sorted([r for r in reviews if r.get('date', '') >= today], key=lambda r: r['date'])
    upcoming = [dict(date=i['due'], what=i.get('short') or shorten(i['text']))
                for i in items if i.get('due') and i.get('status') != 'done']
    if next_run and not any(u['date'] == next_run for u in upcoming):
        upcoming.append(dict(date=next_run, what=next_label))
    upcoming += [dict(date=r['date'], what=r.get('short') or shorten(r['what'])) for r in future_reviews]
    upcoming = sorted(upcoming, key=lambda u: u['date'])[:5]
    next_review = (dict(date=future_reviews[0]['date'], what=future_reviews[0].get('short') or shorten(future_reviews[0]['what']))
                   if future_reviews else None)
    return items, reviews, upcoming, next_review


def decisions_of(items):
    """Open items waiting on a decision, for the home page's 'Needs a decision' list."""
    return [dict(text=i.get('short') or shorten(i['text']), opened=i.get('opened'), due=i.get('due'))
            for i in items if i.get('status') == 'decision'] or None


SCOPE_STATUS = ('ai', 'guardrail', 'fixed', 'not_yet', 'si')


def build_scope(cfg, a, stage, changes, run_date, run_state, run_label):
    """The optimisation map: each lever of the product's ads, who owns it now, and when the AI last changed it.

    A lever counts the plan's changes by type. One that names an owner_kind (the b2b lever: 'business') counts only the
    rows carrying that owner_kind, so it never repeats a consumer count that shares its types (keyword_bids)."""
    def by_type(rows):
        counts = {}
        for c in rows:
            counts[c.get('type')] = counts.get(c.get('type'), 0) + 1
        return counts
    all_counts = by_type(changes)
    overrides = a.get('scope') or {}
    out = []
    for lever in cfg.get('scope', []):
        kind = lever.get('owner_kind')
        counts = by_type([c for c in changes if c.get('owner_kind') == kind]) if kind else all_counts
        status = lever.get('queued' if stage == 'queued' else 'ai', 'none')
        o = overrides.get(lever['id']) or {}
        status = o.get('status', status)
        if status not in SCOPE_STATUS:
            continue
        what = o.get('what') or (lever.get('si_what') if status == 'si' else None) or lever['what']
        row = dict(id=lever['id'], label=lever['label'], what=what, status=status, note=o.get('note'))
        n = sum(counts.get(t, 0) for t in lever.get('types', []))
        if n and run_date:
            row['last_change'] = dict(date=run_date, n=n, label=run_label, state=run_state,
                                      types=[t for t in lever.get('types', []) if counts.get(t)])
        out.append({k: v for k, v in row.items() if v is not None})
    return out


def activity_key(x):
    """Sort activity lines by date, then by the first HH:MM in their time ("about 14:05 UTC", "13:45–14:00 UTC")."""
    m = re.search(r'(\d{1,2}):(\d{2})', str(x.get('time') or ''))
    return (x.get('date', ''), f"{int(m.group(1)):02d}:{m.group(2)}" if m else '')


def just_changed(a, changes, run_date, run_state, run_label, by, approved_by):
    """What has just been done to the product: the latest run's changes, counted by type (or its latest activity),
    plus the product's three most recent activity lines."""
    out = _just_changed(a, changes, run_date, run_state, run_label, by, approved_by)
    acts = sorted(a.get('activity') or [], key=activity_key, reverse=True)[:3]
    if out is not None and acts:
        out['recent'] = [dict(date=x.get('date'), time=x.get('time'), text=shorten(x.get('text', ''), 220)) for x in acts]
    return out


def _just_changed(a, changes, run_date, run_state, run_label, by, approved_by):
    if changes and run_date:
        counts = {}
        for c in changes:
            if c.get('status') == 'skipped':
                continue
            counts[c.get('type')] = counts.get(c.get('type'), 0) + 1
        parts = sorted(counts.items(), key=lambda kv: -kv[1])
        noun = {'Bid change': 'bid changes', 'Negative exact': 'negatives', 'New exact campaign': 'new exact campaigns',
                'Reuse exact campaign': 'reused exact campaigns', 'Pause keyword': 'keywords paused',
                'Budget and top of search': 'budget and top-of-search updates', 'Archive negative': 'negatives archived',
                'New SB video campaign': 'Sponsored Brands video keywords', 'SB bid change': 'Sponsored Brands bid changes',
                'SB pause keyword': 'Sponsored Brands keywords paused'}
        text = ', '.join(f"{n} {noun.get(t, t.lower())}" for t, n in parts[:4])
        verb = 'applied' if run_state == 'applied' else 'waiting for approval'
        d = dt.date.fromisoformat(run_date)
        on = f"{d:%b} {d.day}"
        return dict(date=run_date, label=run_label, state=run_state, by=by, approved_by=approved_by,
                    counts=[[t, n] for t, n in parts], headline=f"{run_label}, {verb} {on}: {text}" if text else f"{run_label}, {verb} {on}")
    acts = sorted(a.get('activity') or [], key=activity_key, reverse=True)
    if acts:
        return dict(date=acts[0].get('date'), label='Latest activity', state=run_state, by=by,
                    headline=shorten(acts[0].get('text', ''), 160))
    return None


def verdict_of(t):
    role, sub = t.get('role'), t.get('sub_role')
    if role == 'Rank':
        return 'invest' if sub == 'Invest' else 'prove'
    return (role or 'leave').lower().replace(' ', '_')


def verdicts(cfg):
    th, pl, bu = cfg['thresholds'], cfg['placement'], cfg['budgets']
    # top of search on a rank campaign is the standing policy (Kim, 2026-10-20) while placement.rank_tos_standing is on
    standing = pl.get('rank_tos_standing') or {}
    policy = lambda role: (None if rank_tos(pl, role) is None else
                           f"top of search +{rank_tos(pl, role):g}% (standing policy, {standing.get('by')} {standing.get('on')})")
    return [
        ['invest', 'Keep investing', f"Beats the market (index {th['index_invest']}+) with {th['invest_min_volume']}+ searches in 12 weeks and "
                                     f"{th['invest_min_purchases']}+ purchases: its own exact campaign; "
                                     f"{policy('Invest') or 'placements reviewed separately'}, ${bu['invest_per_day']}/day."],
        ['prove', 'Prove first', f"Beats the market on fewer than {th['invest_min_purchases']} purchases: its own exact campaign at "
                                 f"${bu['prove_per_day']}/day until it proves itself; {policy('Prove first') or 'no automatic placement boost'}."],
        ['defend', 'Defend', f"Already strong ({th['defend_impression_share'] * 100:.0f}%+ impression share, "
                             f"{th['defend_organic_share'] * 100:.0f}%+ organic): breakeven bid, no extra push."],
        ['hold', 'Bid to breakeven', f"Converts about like the market (index {th['index_hold']} to {th['index_invest']}): bid = profit per order × "
                                     f"its conversion, so it pays for itself. With 2+ orders on its search it bids Amazon's suggested mid instead, "
                                     f"to stay visible (decision 177)."],
        ['trim', 'Lower bids', f"Converts worse than the market (index under {th['index_hold']}) on {th['trim_min_clicks']}+ clicks: "
                               f"{th['trim_factor'] * 100:.0f}% of breakeven; paused below index {th['index_pause']} on {th['pause_min_clicks']}+ clicks."],
        ['test', 'Testing', f"Too few of our clicks to judge, but {th['invest_min_volume']}+ searches or an ad order: breakeven at the market's "
                            f"conversion, at least ${th['test_floor_bid']:.2f}. A new keyword bids Amazon's suggested mid during its launch test "
                            f"(until 2 expected orders at the product's ad conversion, 15 to 60 clicks; 3 with one order; decisions 177 and 178)."],
        ['negate', 'Negate', 'Not our product (relevance lists and the negative audit): negated after the audit\'s approval table.'],
        ['leave', 'Too small to judge', 'Little volume and no data yet: left alone.'],
    ]


def lanes_era(plan):
    """True for a run planned with the lanes (C7: its plan.json summary[0] has `lanes`). Such a run never falls back to
    "everything applied": without payloads/applied_rows.json nothing of it went out."""
    first = (plan.get('summary') or [{}])[0]
    return isinstance(first, dict) and 'lanes' in first


def applied_marks(run_dir, plan):
    """For a page published --state applied (B7, I8, C7): a function giving each plan row its (status, note), or None for
    an older run (no summary.lanes) without <run>/payloads/applied_rows.json, whose every row is marked applied, as
    before. A run planned with the lanes and no record went out with nothing: its rows are marked by lane, none applied.

    A row `dashboard.py applied` recorded as gone out is 'applied'. Every other row says why it didn't go out:
    'declined' when its latest decision on this run's bids item in <run>/reviews.json is a decline; 'held' when a lock
    holds it (locked_until) or the planner holds it until the next run (monitor); 'not applied' for an enabled run's
    automatic row the apply didn't record; else (a person's row, or any row of a shadow run) 'waiting for a person'."""
    path = os.path.join(run_dir, 'payloads', APPLIED_ROWS)
    if not os.path.exists(path) and not lanes_era(plan):
        return None
    applied = read_applied(path)  # {} without the file: nothing went out
    shadow = (plan.get('summary') or [{}])[0].get('shadow') is not False
    declined = {}
    entries = load_json(os.path.join(run_dir, 'reviews.json'))
    entries = entries.get('entries') if isinstance(entries, dict) else entries  # C6's dated shape, or an older bare list
    item = next((i for i in plan.get('human_review') or [] if isinstance(i, dict) and i.get('kind') == 'bid'), None)
    if isinstance(entries, list) and item is not None:
        decided, _, _ = latest_decisions(item, entries)
        declined = {rid: e for rid, e in decided.items() if e['decision'] == 'decline'}

    def mark(c):
        rid = c.get('row_id')
        if rid in applied:
            return 'applied', None
        if rid in declined:
            return 'declined', f"Not applied: declined by {declined[rid]['by'].strip()}"
        if c.get('locked_until'):
            who = ', '.join(str(v) for v in (c.get('decided_by'), c.get('decided_on')) if v)
            return 'held', 'Not applied: held by an earlier decision' + (f' ({who})' if who else '')
        if c.get('lane') == 'monitor':
            return 'held', 'Not applied: held until the next run'
        if c.get('lane') == 'auto' and not shadow:
            return 'not applied', 'Not applied: not recorded as applied'
        return 'waiting for a person', 'Not applied: waiting for a person'
    return mark


def build_doc(asin, run_dir, state, label, date, by, data, due_plan=None):
    cfg = config()
    a = load_json(os.path.join(data_dir(cfg, data), 'asins', f'{asin}.json'))
    plan = load_json(os.path.join(run_dir, 'plan.json'))
    if a is None or plan is None:
        raise SystemExit(f'missing product file or {run_dir}/plan.json')
    # For Growth, on the STORED item before the plan's items are merged (R37): the run's gate counts (and its anchor, when
    # the file has none) are kept (R6); Growth's saved clicks move the item on; and a picked-up item whose copy changed in
    # this run's listing.json, against the snapshot it was built on, is resolved (spec 4). The plan's own growth item
    # was built on this run's listing, so judged after the merge the new copy would be compared with itself.
    stored_growth = copy.deepcopy(growth_item(a.get('human_review')))
    store_growth_run(a, run_dir)
    auto_enable_growth(a, date, cfg)
    closed_now = growth_run_steps(a, run_dir, asin, date, cfg)
    if 'human_review' in plan:
        # a plan made with lanes passes its own run date (the date its bids item id carries, not the publish date), so a
        # run with nothing to decide still supersedes the older runs' bids items; an older plan passes none. The product
        # file goes in too: on an AI-managed product the For Growth item supersedes listing-conversion-gap.
        first = (plan.get('summary') or [{}])[0]
        run_date = first.get('review_date') if isinstance(first, dict) and isinstance(first.get('lanes'), dict) else None
        incoming = plan['human_review']
        if closed_now:
            # R37: the pass closed in this publish, so the plan's growth item (planned before the close: its block, its
            # flag and its snapshot predate the change) is not merged; the resolved item goes in its place and stands
            # (the same block, so the merge keeps it), and a flag on the new copy waits for a run after the quiet window
            incoming = [growth_item(a['human_review']) if isinstance(i, dict) and i.get('id') == growth.GROWTH_ID else i
                        for i in incoming]
        a['human_review'] = merge_human_review(a.get('human_review', []), incoming, date, run_date=run_date, product=a)
    # a flag the merged item adds gets an activity line (R7)
    for term in new_flags(stored_growth, growth_item(a.get('human_review'))):
        add_activity(a, f'rotate-out flag on {product_name(a, asin)}: {term}')
    applied = load_json(os.path.join(run_dir, 'applied.json'), {}) or {}
    summ = (plan.get('summary') or [{}])[0]
    th = cfg['thresholds']
    reg = dict(bid_owner='AI', owner_since=(a.get('si') or {}).get('onboarded'))
    reg.update(a.get('registry') or {})

    # --- latest run: the plan's changes, with what the apply did differently
    texts = Texts()
    skipped = {(s.get('type', 'Negative exact'), s.get('keyword'), str(s.get('ad_group_id') or s.get('campaign_id') or '')): s
               for s in applied.get('skipped', [])}
    retype = {(r.get('type'), r.get('keyword')): r for r in applied.get('retype', []) if not r.get('keyword_id')}
    retype_id = {str(r['keyword_id']): r for r in applied.get('retype', []) if r.get('keyword_id')}  # one keyword, not every row with its text
    marks = applied_marks(run_dir, plan) if state == 'applied' else None
    rows, raw_changes = [], []
    for c in list(plan.get('changes', [])) + list(applied.get('extra', [])):
        c = dict(c)
        if marks is not None and c.get('row_id') is not None:
            c['status'], note = marks(c)  # B7: only what went out reads applied
            if note:
                c['note'] = note
        c.setdefault('status', 'applied' if state == 'applied' else 'proposed')
        k = (c.get('type'), c.get('keyword'), str(c.get('ad_group_id') or c.get('campaign_id') or ''))
        if k in skipped:
            c['status'], c['note'] = 'skipped', skipped[k].get('why') or 'Not applied'
        rt = retype_id.get(str(c.get('keyword_id'))) if c.get('keyword_id') and str(c.get('keyword_id')) in retype_id else retype.get((c.get('type'), c.get('keyword')))
        if rt:
            for key, v in rt.items():
                if key not in ('type', 'keyword', 'to', 'keyword_id'):
                    c[key] = v
            c['type'] = rt.get('to', c['type'])
        if c.get('type') != 'Stop-loss review':
            c.pop('how', None)
        raw_changes.append(c)
        row = {}
        for key in CHANGE_KEYS:
            v = c.get(key)
            if v is None or v == '':
                continue
            row[key] = texts(v) if key in TEXT_KEYS else rnd(v)
        rows.append(row)

    # --- invest searches: live (or proposed) settings, baselines and review dates
    log = a.get('invest_log') or {}
    sug, camp_ids = {}, {}
    for c in plan.get('changes', []):
        kw = c.get('keyword')
        if kw and c.get('sug_median') is not None and kw not in sug:
            sug[kw] = (c.get('sug_low'), c.get('sug_median'), c.get('sug_high'))
        if kw and c.get('type') in ('Budget and top of search', 'New exact campaign', 'Reuse exact campaign') and c.get('campaign_id'):
            camp_ids[kw] = c['campaign_id']
    for r in applied.get('retype', []):
        if r.get('campaign_id'):
            camp_ids[r['keyword']] = r['campaign_id']
    # the consumer invest searches: a business re-rank row (owner_kind 'business', its forecast under its own key) has its
    # own log and campaign, which this card doesn't read; it shows on the Bids card as its Business invest row
    due = {}
    if due_plan:
        later = load_json(due_plan, {})
        due = {r['keyword']: r for r in later.get('rerank', []) if r.get('owner_kind') != 'business'}
    months = th.get('stop_loss_months') or [3, 6, 9, 12]   # the consumer stop-loss checkpoints (decision 142)
    invest = []
    for r in plan.get('rerank', []):
        if r.get('owner_kind') == 'business':
            continue
        kw = r['keyword']
        lg = log.get(kw, {})
        if marks is not None:
            # SB builds, negatives and SI work do not activate a consumer SP investment. A held SP change also
            # makes rerank's planned prices unsafe to label live, even when an older investment clock exists.
            sp_settings = [c for c in raw_changes if c.get('keyword') == kw
                           and c.get('owner_kind') != 'business'
                           and c.get('type') in ('New exact campaign', 'Reuse exact campaign', 'New exact keyword',
                                                 'Bid change', 'Budget and top of search', 'Budget step', 'Pause keyword')]
            if any(c.get('status') != 'applied' or c.get('type') == 'Pause keyword' for c in sp_settings):
                continue
            since = lg.get('since')
            existing = bool(_iso_day(since) and since <= date)
            activated = any(c.get('status') == 'applied'
                            and (c.get('role') in ('Invest', 'Prove first')
                                 or (c.get('type') in ('New exact campaign', 'Reuse exact campaign')
                                     and r.get('role') in ('Invest', 'Prove first')))
                            for c in sp_settings)
            if not existing and not activated:
                continue
        lo, med, hi = sug.get(kw, (None, None, None))
        row = dict(keyword=kw, role=r.get('role'), since=lg.get('since'), bid=r.get('bid'), tos=r.get('tos'), budget=r.get('budget'),
                   sug_low=lo, sug_median=med, sug_high=hi, month_searches=r.get('month_searches'),
                   index_then=lg.get('index_then'), imp_share_then=lg.get('imp_share_then'), organic_then=lg.get('organic_then'),
                   rank_then=lg.get('rank_then'), rank_now=lg.get('rank_now'), campaign_id=camp_ids.get(kw))
        next_cp = next((m for m in months if m > (lg.get('checkpoint') or 0)), None)
        if lg.get('since') and next_cp:
            row['review_on'] = add_days(lg['since'], round(next_cp * 365 / 12))
        d = due.get(kw)
        if d and d.get('bid') is not None and r.get('bid') is not None and abs(d['bid'] - r['bid']) >= 0.02:
            row['due_bid'] = d['bid']
            row['due_note'] = f"next run: ${d['bid']:.2f} (median, or breakeven if higher)"
        invest.append({k: rnd(v) for k, v in row.items() if v is not None})
    role_order = {'Invest': 0, 'Prove first': 1}
    invest.sort(key=lambda x: (role_order.get(x.get('role'), 2), -(x.get('budget') or 0), -(x.get('month_searches') or 0)))
    roles = {}
    for r in invest:
        roles[r.get('role')] = roles.get(r.get('role'), 0) + 1

    # --- search terms by verdict
    ttexts = Texts()
    term_rows = []
    for t in plan.get('terms', []):
        v = dict(t, verdict=verdict_of(t))
        term_rows.append([ttexts(v.get(c)) if c in ('why', 'index_basis') else rnd(v.get(c)) for c in TERM_COLS])

    # --- harvest
    h = dict(a.get('harvest') or {})
    ph = plan.get('harvest') or {}
    harvest = dict(campaign_id=h.get('campaign_id'), ad_group_id=h.get('ad_group_id'), default_bid_live=h.get('default_bid'),
                   default_bid_computed=ph.get('default_bid'), median_of_medians=ph.get('median_of_medians'),
                   breakeven_click_avg=ph.get('breakeven_click_avg'), median_high=ph.get('median_high'), gate=ph.get('gate'),
                   gate_band=ph.get('gate_band'), priced_searches=ph.get('priced_searches'),
                   import_rule_id=ph.get('import_rule_id') or cfg['scale_insights']['import_rules_by_gate'].get(str(ph.get('gate_band'))),
                   strategy_id=h.get('strategy_id') or cfg['scale_insights']['strategies'].get('harvest_exact_import'),
                   strategy_status=h.get('strategy_status'), active=h.get('active'), budget_day=h.get('budget_day', cfg['budgets'].get('harvest_per_day')))
    harvest = {k: rnd(v) for k, v in harvest.items() if v is not None}

    # --- dates
    today = dt.date.today().isoformat()
    next_run = reg.get('next_run') or add_days(date, 7)
    items, reviews, upcoming, next_review = dated(a, next_run, 'Weekly run')

    last_applied = dict(date=date, label=label) if state == 'applied' else a.get('last_applied')
    brief = a.get('brief') or {}
    # with the applied record, the optimisation map and the headline count only what went out (or, proposed, what is planned)
    done = raw_changes if marks is None else [c for c in raw_changes if c.get('status') in ('applied', 'proposed')]
    page_stage = 'queued' if reg.get('stage') in ('queued', 'onboarding') else 'ai'
    scope = build_scope(cfg, a, page_stage, done, date, state, label)
    changed = just_changed(a, done, date, state, label, by, applied.get('approved_by'))
    card = dict(product=a.get('product'), sku=a.get('sku'), title=a.get('title'), **identity(cfg, a), stage=page_stage, bid_owner=reg.get('bid_owner'),
                just_changed=dict(date=changed['date'], headline=changed['headline'], by=changed.get('by')) if changed else None,
                scope_counts={s: sum(1 for x in scope if x['status'] == s) for s in SCOPE_STATUS if any(x['status'] == s for x in scope)},
                owner_since=reg.get('owner_since'), headline=brief.get('headline'), last_applied=last_applied,
                pending=dict(date=date, label=label) if state == 'proposed' else None, next_run=next_run,
                next_review=next_review,
                invest_count=len(invest), invest_roles=roles,
                invest_budget_day=rnd(sum(r.get('budget') or 0 for r in invest)) if invest else None,
                invest_plan_day=summ.get('invest_plan_day'), monitor=monitor_card(a), rank=rank_card(a),
                open_items=sum(1 for i in items if i.get('status') != 'done'), decisions=decisions_of(items), upcoming=upcoming,
                growth=growth_card(a, cfg))

    run = dict(id=os.path.basename(os.path.normpath(run_dir)), date=date, state=state, label=label,
               approved_by=applied.get('approved_by'), window=applied.get('window') or summ.get('window'),
               summary={k: summ.get(k) for k in TEAM_FIELDS if summ.get(k) is not None},
               notes=applied.get('notes', []), change_sets=applied.get('change_sets', []),
               rerank=[{k: rnd(v) for k, v in r.items() if k not in ('product', 'asin')} for r in plan.get('rerank', [])],
               changes=rows, text=texts.list)
    inv_note = (('Verified current consumer Sponsored Products investment settings. ' if invest
                 else 'No verified consumer Sponsored Products investment settings in this run. Held proposals and '
                      'Sponsored Brands creations are not active SP investments. ') if state == 'applied'
                else 'Settings in the plan waiting for approval; nothing changes until it is approved. ')
    inv_note += (f"Invest searches may cost more than they bring back while they climb. The brake is the stop-loss: at "
                 f"months {', '.join(str(m) for m in months)} of investing, a search with no gain in organic rank or organic "
                 f"purchases since the last checkpoint steps down to Hold (the AI applies the step-down itself and notes it).")
    ids = [['ASIN · SKU', f"{asin} · {a.get('sku')}"],
           ['Amazon Ads profile', cfg['amazon_ads'].get('profile')],
           ['Portfolio', f"{cfg.get('portfolio_name')} ({cfg.get('portfolio_id')})"],
           ['Harvest campaign · ad group', f"{h.get('campaign_id')} · {h.get('ad_group_id')}"],
           ['Rank Radar (DataDive)', a.get('rank_radar_id')],
           ['Scale Insights strategies', ' · '.join(f'{k.replace("_", " ")} {v}' for k, v in cfg['scale_insights']['strategies'].items())],
           ['Scale Insights import rules', ' · '.join(f'gate {float(k) * 100:.0f}%: {v}' for k, v in cfg['scale_insights']['import_rules_by_gate'].items())],
           ['Registry', cfg.get('registry')]]
    inputs = summ.get('inputs') or {}
    sources = []
    if inputs:
        sources.append(f"Run {run['id']}: SQP {inputs.get('sqp')} searches (12 weeks), {inputs.get('search_terms')} search-term rows and "
                       f"{inputs.get('keywords')} keywords (90 days), {inputs.get('suggested')} searches priced by Amazon.")
    sources += ['Index = our conversion ÷ the market\'s on the same search (SQP first, the search-term report second), '
                f"shrunk toward the market with a {th['prior_clicks']}-click prior.",
                'Bids and budgets: Amazon Ads via MarketplaceAdPros. SQP, search terms and product costs: Scale Insights. '
                'Organic rank: DataDive Rank Radar.',
                'The scope above describes each workflow. Only rows explicitly recorded as applied in the latest run are completed changes; other proposals remain separate.']
    doc = dict(schema=1, asin=asin, sku=a.get('sku'), product=a.get('product'), title=a.get('title'), **identity(cfg, a), published_by=by,
               card=card, registry=reg,
               economics=dict(price=a.get('price'), profit_per_unit=a.get('profit_per_unit'), economics_as_of=a.get('economics_as_of'),
                              breakeven_click_avg=summ.get('breakeven_click_avg'), asin_ad_cvr=summ.get('asin_ad_cvr'),
                              asin_market_cvr=summ.get('asin_market_cvr'), launch_date=a.get('launch_date'), baseline=a.get('baseline')),
               brief=brief, monitor=a.get('monitor'), rank=a.get('rank'), scope=scope, just_changed=changed,
               activity_note=changed['headline'] if changed else None,
               invest=dict(as_of=date, note=inv_note, rows=invest, due_as_of=today if due_plan else None),
               stop_loss=[{k: v for k, v in s.items() if k not in ('product', 'asin')} for s in plan.get('stop_loss', [])],
               harvest=harvest, run=run,
               terms=dict(window=applied.get('terms_window') or 'SQP 12 weeks and search terms 90 days, as pulled for this run',
                          cols=TERM_COLS, rows=term_rows, text=ttexts.list, verdicts=verdicts(cfg)),
               open_items=items, activity=a.get('activity') or [], reviews=reviews, rules=RULES, ids=ids, sources=sources)
    attach_human_review(doc, a)
    if a.get('ui_evidence'):
        doc['ui_evidence'] = a['ui_evidence']
    doc['placement_review'] = plan.get('placement_review')
    doc['card']['placement_review_summary'] = (plan.get('placement_review') or {}).get('summary')
    return doc, a


def lineup_note(reg, m):
    """The activity line for a lined-up product's page update: its queue place and last 30 days."""
    note = f"Lined up #{reg.get('queue')}, still on Scale Insights rules"
    if m:
        money = lambda v: ('−' if v < 0 else '') + f"${abs(v):,.0f}"
        note += (f"; last 30 days to {m.get('end')}: {money(m.get('ad_spend', 0))} ads, ACOS {m.get('acos', 0) * 100:.0f}% "
                 f"(breakeven {m.get('breakeven_acos', 0) * 100:.0f}%), {money(m.get('profit', 0))} profit")
    return note


def build_lineup_doc(asin, date, by, data):
    """The page of a product lined up for AI bidding: still on Scale Insights bid rules, monitored until its onboarding run."""
    cfg = config()
    a = load_json(os.path.join(data_dir(cfg, data), 'asins', f'{asin}.json'))
    if a is None:
        raise SystemExit(f'missing product file data/asins/{asin}.json')
    reg = dict(bid_owner='Scale Insights', stage='queued')
    reg.update(a.get('registry') or {})
    if reg.get('stage') != 'queued':
        raise SystemExit(f'{asin}: registry.stage is {reg.get("stage")!r}; lineup publishes only queued products (use publish after onboarding)')
    items, reviews, upcoming, next_review = dated(a, reg.get('onboard_on'), 'Onboarding run (AI takes over bids)')
    brief = a.get('brief') or {}
    scope = build_scope(cfg, a, 'queued', [], None, 'queued', None)
    changed = just_changed(a, [], None, 'queued', None, by, None)
    card = dict(product=a.get('product'), sku=a.get('sku'), title=a.get('title'), **identity(cfg, a), stage='queued', queue=reg.get('queue'),
                just_changed=dict(date=changed['date'], headline=changed['headline'], by=changed.get('by')) if changed else None,
                bid_owner=reg.get('bid_owner'), headline=brief.get('headline'), onboard_on=reg.get('onboard_on'),
                next_review=next_review, monitor=monitor_card(a), rank=rank_card(a),
                open_items=sum(1 for i in items if i.get('status') != 'done'), decisions=decisions_of(items), upcoming=upcoming)
    ids = [['ASIN · SKU', f"{asin} · {a.get('sku')}"],
           ['Amazon Ads profile', cfg['amazon_ads'].get('profile')],
           ['Bids today', 'Scale Insights bid rules (the old setup), until the onboarding run'],
           ['Rank Radar (DataDive)', a.get('rank_radar_id')],
           ['Registry', cfg.get('registry')]]
    sources = ['Last 30 days: Scale Insights sales data (sales, orders, ad spend and ad sales, organic share, profit after all '
               'costs). Breakeven ACOS = profit per unit ÷ list price, from Scale Insights product costs.',
               'The onboarding run adds the invest searches, every bid, the harvest campaign and the Scale Insights '
               'guardrails; until then this page only monitors.']
    doc = dict(schema=1, asin=asin, sku=a.get('sku'), product=a.get('product'), title=a.get('title'), **identity(cfg, a), published_by=by,
               card=card, registry=reg,
               economics=dict(price=a.get('price'), profit_per_unit=a.get('profit_per_unit'), economics_as_of=a.get('economics_as_of'),
                              launch_date=a.get('launch_date'), baseline=a.get('baseline')),
               brief=brief, monitor=a.get('monitor'), rank=a.get('rank'), scope=scope, just_changed=changed,
               activity_note=lineup_note(reg, a.get('monitor')),
               run=dict(label='Lined up for AI bidding', state='queued', date=date),
               open_items=items, activity=a.get('activity') or [], reviews=reviews, rules=RULES, ids=ids, sources=sources)
    attach_human_review(doc, a)
    return doc, a


def refresh_doc(live, a, cfg, note):
    """An AI-managed product's live page, with everything that comes from the product file rebuilt: name and group,
    registry, brief, last 30 days, open items, activity, the optimisation map and the card. The latest run's tables
    (changes, invest searches, search terms, harvest maths) stay as published, since its run folder is not in git."""
    doc = dict(live)
    for k in ('published_at', 'version', 'published_by'):
        doc.pop(k, None)
    run = doc.get('run') or {}
    reg = dict(doc.get('registry') or {})
    reg.update(a.get('registry') or {})
    next_run = reg.get('next_run') or (doc.get('card') or {}).get('next_run')
    items, reviews, upcoming, next_review = dated(a, next_run, 'Weekly run')
    changes = run.get('changes') or []
    # Keep held rows in the table, but count only verified applied rows in the recap and scope.
    if run.get('state') == 'applied' and any(c.get('status') is not None for c in changes):
        changes = [c for c in changes if c.get('status') == 'applied']
    page_stage = 'queued' if reg.get('stage') in ('queued', 'onboarding') else 'ai'
    scope = build_scope(cfg, a, page_stage, changes, run.get('date'), run.get('state'), run.get('label'))
    prev = doc.get('just_changed') or {}
    changed = just_changed(a, changes, run.get('date'), run.get('state'), run.get('label'), prev.get('by'), run.get('approved_by'))
    econ = dict(doc.get('economics') or {})
    econ.update(price=a.get('price'), profit_per_unit=a.get('profit_per_unit'), economics_as_of=a.get('economics_as_of'),
                launch_date=a.get('launch_date'), baseline=a.get('baseline'))
    h = dict(doc.get('harvest') or {})
    ah = a.get('harvest') or {}
    h.update({k: v for k, v in dict(default_bid_live=ah.get('default_bid'), strategy_id=ah.get('strategy_id'), import_rule_id=ah.get('import_rule_id'), strategy_status=ah.get('strategy_status'),
                                     active=ah.get('active')).items() if v is not None})
    brief = a.get('brief') or {}
    card = dict(doc.get('card') or {})
    card.update(product=a.get('product'), sku=a.get('sku'), title=a.get('title'), **identity(cfg, a), stage=page_stage, bid_owner=reg.get('bid_owner'),
                owner_since=reg.get('owner_since'), headline=brief.get('headline'), last_applied=a.get('last_applied') or card.get('last_applied'),
                just_changed=dict(date=changed['date'], headline=changed['headline'], by=changed.get('by')) if changed else None,
                scope_counts={s: sum(1 for x in scope if x['status'] == s) for s in SCOPE_STATUS if any(x['status'] == s for x in scope)},
                next_run=next_run, next_review=next_review, monitor=monitor_card(a), rank=rank_card(a),
                open_items=sum(1 for i in items if i.get('status') != 'done'), decisions=decisions_of(items), upcoming=upcoming,
                growth=growth_card(a, cfg))
    doc.update(sku=a.get('sku'), product=a.get('product'), title=a.get('title'), **identity(cfg, a), card=card, registry=reg,
               economics=econ, brief=brief, monitor=a.get('monitor'), rank=a.get('rank'), scope=scope, just_changed=changed, harvest=h,
               ids=[[k, a.get('rank_radar_id') if k == 'Rank Radar (DataDive)' else v] for k, v in (doc.get('ids') or [])],
               open_items=items, activity=a.get('activity') or [], reviews=reviews, publish_kind='Page refresh',
               activity_note=note or 'Page refreshed from the product file (brief, open items, activity, last 30 days)')
    attach_human_review(doc, a)
    return doc


def record_run_history(product, run_dir, keep=26):
    """What a run teaches the product file, set on the `product` dict (the caller writes the file): the run's SQP totals
    appended to `sqp_history` when they are for a newer week than its newest entry (the same week or an older one never
    adds a second copy, so refreshing twice is safe), trimmed to the last `keep`; and `data_stage` set to the run's stage,
    except that a recorded 'mature' stays (stage.volatile_week and stage.data_stage read both on the next run). Reads
    sqp_totals.json and plan.json's summary[0]['stage'], which plan.py leaves in the run folder. Returns what it did,
    with `notes` for any part the folder could not give (that part is left as it was)."""
    notes = []
    appended = False
    totals = load_json(os.path.join(run_dir, 'sqp_totals.json'))
    if totals is None:
        notes.append('the run folder has no sqp_totals.json: sqp_history left as it is')
    elif not totals.get('data_through'):
        notes.append('sqp_totals.json has no data_through, so there is no week to record: sqp_history left as it is')
    else:
        history = list(product.get('sqp_history') or [])
        newest = max((e.get('data_through') or '' for e in history), default='')    # as stage.volatile_week reads it
        if totals['data_through'] > newest:
            history.append({k: totals.get(k) for k in ('data_through', 'our_clicks', 'our_purchases', 'queries')})
            product['sqp_history'] = history[-keep:]
            appended = True
    plan = load_json(os.path.join(run_dir, 'plan.json')) or {}
    stage = ((plan.get('summary') or [{}])[0].get('stage') or {}).get('stage')
    before = product.get('data_stage')
    if not stage:
        notes.append("the run's plan.json has no data stage: data_stage left as it is")
    elif before != 'mature':
        product['data_stage'] = stage
    after = product.get('data_stage')
    return dict(sqp_history_appended=appended, data_stage=after, data_stage_changed=after != before, notes=notes)


# ---- For Growth: the dates on the card, the run's gate counts, Growth's clicks, the close on a listing change ----------
# docs/superpowers/specs/2026-10-22-for-growth-tab-design.md sections 1, 2, 2b and 4, and the launch design's 4e
# (docs/superpowers/specs/2026-10-20-launch-process-ai-growth-design.md). growth.py holds the rules; this part reads and
# writes the product file and the run folder for them.

GROWTH_STEPS = ('open', 'in_progress', 'copy_pushed')   # Growth's clicks move the item forward; only an undo steps back
STEP_WORDS = {'in_progress': 'Picked up', 'copy_pushed': 'Copy pushed'}
UNDO_TO = {'open': 'not picked up', 'in_progress': 'picked up'}   # where an undo leaves the item, for its history line
CLOSABLE = ('in_progress', 'copy_pushed')   # a listing change closes an item someone picked up, never an open one
ITEM_STATUSES = 'item_statuses.json'   # <run>/item_statuses.json, {asin, saved_at, entries}: written by `reviews --save`
WINDOW_KEYS = ('first_pass_days', 'pass_floor_weeks', 'pass_ceiling_weeks')   # config.json growth keys due_dates reads


def growth_item(items):
    """The For Growth item (id for-growth, kind growth) in a human_review list, or None."""
    return next((i for i in items or [] if isinstance(i, dict) and i.get('id') == growth.GROWTH_ID
                 and i.get('kind') == 'growth'), None)


def growth_block(product):
    """The product file's growth block, as a dict set on the product (so changes to it are the product's, in place)."""
    if not isinstance(product.get('growth'), dict):
        product['growth'] = {}
    return product['growth']


def add_activity(product, text):
    """A line in the product file's activity (the page and the card show the latest), dated and timed in Singapore like
    the other lines."""
    now = utc_now() + SGT
    line = dict(date=now.strftime('%Y-%m-%d'), time=now.strftime('%H:%M SGT'), text=text)
    product['activity'] = list(product.get('activity') or []) + [line]
    return line


def product_name(product, asin=None):
    return product.get('name') or product.get('product') or asin or product.get('asin')


def growth_card(product, cfg):
    """card.growth = {enabled, anchor, next_pass} (R8): what the For Growth tab's Scheduled group (every product's dates,
    from /api/products) and the product page's "listing pass" line read before any item exists. `enabled` is
    growth.enabled (else config growth.enabled_default); `anchor` the stored growth.anchor or None; `next_pass` the stored
    window, else, when the file has an anchor (or a resolved pass) but no window, the one growth.due_dates gives: before a
    resolved pass both dates are the first due date. In evidence mode (decision 124, 2026-10-25) a product with no
    resolved pass always gets the computed window: no earlier date, `by` the ceiling, on_evidence true. None when
    nothing is known."""
    g = product.get('growth') if isinstance(product.get('growth'), dict) else {}
    settings = cfg.get('growth') if isinstance(cfg.get('growth'), dict) else {}
    enabled = g.get('enabled', settings.get('enabled_default', False)) is True
    the_anchor = g['anchor'] if isinstance(g.get('anchor'), dict) and g['anchor'].get('date') else None
    window = g.get('next_pass') if isinstance(g.get('next_pass'), dict) and any(g['next_pass'].values()) else None
    if (growth.evidence_mode(cfg) and not growth.resolved_passes(product)
            and all(k in settings for k in WINDOW_KEYS)):
        # the first pass waits for proven SKC keywords (decision 124): a stored day-56 window is stale, so the card
        # reads {no_earlier_than: None, by: the ceiling, on_evidence: True}
        computed = growth.due_dates(product, cfg)['next_pass']
        return dict(enabled=enabled, anchor=the_anchor, next_pass=computed if computed.get('by') else None)
    if window is None and (the_anchor or growth.resolved_passes(product)) and all(k in settings for k in WINDOW_KEYS):
        computed = growth.due_dates(product, cfg)['next_pass']
        window = computed if any(computed.values()) else None
    return dict(enabled=enabled, anchor=the_anchor, next_pass=window)


def store_growth_run(product, run_dir):
    """R6: what a run's growth.json (plan.py, every run) leaves in the product file, set on `product` (the caller writes
    the file): the evidence gate's candidates, every run, so the two-run persistence of spec 2b survives from one weekly
    run to the next, except counts dated on or before the last listing change (they judged the old copy, and the close
    cleared them: a run published again must not bring them back); and the anchor only when the file has none (never
    over a stored one, above all one set by hand). Returns {growth_json, candidates, anchor}: whether the run had a
    growth.json, and what was stored. A growth.json for another product stops."""
    path = os.path.join(run_dir, 'growth.json')
    doc = load_json(path)
    done = dict(growth_json=isinstance(doc, dict), candidates=False, anchor=False)
    if not isinstance(doc, dict):
        return done
    if doc.get('asin') and product.get('asin') and doc['asin'] != product['asin']:
        raise SystemExit(f"{path} is for {doc['asin']}, not {product['asin']}: nothing stored")
    found = doc.get('candidates')
    last = growth.last_listing_change(product)
    stale = bool(last) and isinstance(found, dict) and bool(found.get('date')) and str(found['date']) <= last
    if isinstance(found, dict) and not stale:
        growth_block(product)['candidates'] = found
        done['candidates'] = True
    stored = (product.get('growth') or {}).get('anchor') if isinstance(product.get('growth'), dict) else None
    fresh = doc.get('anchor')
    if not (isinstance(stored, dict) and stored.get('date')) and isinstance(fresh, dict) and fresh.get('date'):
        growth_block(product)['anchor'] = fresh
        done['anchor'] = True
    return done


def saved_item_statuses(run_dir, asin):
    """<run>/item_statuses.json's entries (Growth's clicks, as `reviews --save` read them), or None when the run has
    none. One saved for another product stops: every product's item is for-growth, so its clicks would land here."""
    path = os.path.join(run_dir, ITEM_STATUSES)
    data = load_json(path)
    if data is None:
        return None
    held = data.get('asin') if isinstance(data, dict) else None
    if held != asin or not isinstance(data.get('entries'), list):
        raise SystemExit(f'{path} holds item statuses for {held!r}, not {asin}: save them again with '
                         f'dashboard.py reviews --asin {asin} --save <run>/reviews.json. Nothing done.')
    return data['entries']


def _sgt_day(at):
    """An ISO UTC time as its Singapore date (YYYY-MM-DD), or None when it is unreadable."""
    moment = _moment(at)
    return (moment + SGT).date().isoformat() if moment else None


def apply_statuses(items, entries):
    """Growth's clicks on the dashboard (GET /api/items/<ASIN>: {item_id, status, by, at, note}, oldest first) on the
    For Growth items, as a new list (the input is left alone).

    Never onto a closed item. The entries are read oldest first: a click moves an open, picked-up or copy-pushed item to
    its step when it is at or past the item's (open -> in_progress -> copy_pushed); an undo (undo: true, the dashboard's
    "Undo" button) moves it back exactly one step (copy_pushed -> in_progress, in_progress -> open). The last one that
    moved it becomes status, status_by and status_at, with one history line. A plain step back, any other status
    ('resolved' is the AI's alone, on a listing change) and an entry for another item are ignored; every other kind of
    item is left as it is. R33: an entry counts only when its `at`, as a Singapore date, is
    on or after the item's growth.opened_on (the day its pass opened: the item id is the same every pass, so an earlier
    click was the last pass's); an item without opened_on counts every entry. Applied again, nothing more changes."""
    out = copy.deepcopy(items)
    for item in out:
        if not isinstance(item, dict) or item.get('kind') != 'growth' or item.get('status') not in GROWTH_STEPS:
            continue
        opened = (item.get('growth') or {}).get('opened_on')
        step, win = GROWTH_STEPS.index(item['status']), None
        for e in entries or []:
            if not isinstance(e, dict) or e.get('item_id') != item.get('id') or e.get('status') not in GROWTH_STEPS:
                continue
            if opened and (_sgt_day(e.get('at')) or '') < opened:
                continue
            if e.get('undo') is True:
                if GROWTH_STEPS.index(e['status']) == step - 1:
                    step, win = step - 1, e
            elif e['status'] in STEP_WORDS and GROWTH_STEPS.index(e['status']) >= step:
                step, win = GROWTH_STEPS.index(e['status']), e
        if win is None or (item['status'], item.get('status_by'), item.get('status_at')) == (win['status'], win.get('by'),
                                                                                             win.get('at')):
            continue
        item.update(status=win['status'], status_by=win.get('by'), status_at=win.get('at'))
        if win.get('undo') is True:
            undid = STEP_WORDS[GROWTH_STEPS[GROWTH_STEPS.index(win['status']) + 1]]
            note = f"{undid} undone by {win.get('by')} on the dashboard, back to {UNDO_TO[win['status']]}"
        else:
            note = f"{STEP_WORDS[win['status']]} by {win.get('by')} on the dashboard"
        note += f": {win['note']}" if win.get('note') else ''
        item['history'] = list(item.get('history') or []) + [
            dict(date=_sgt_day(win.get('at')) or sgt_today(), status=win['status'], owner=item.get('owner'), note=note)]
    return out


def _flat(text):
    """A surface's text with its spacing collapsed, or None when there is none to compare."""
    return ' '.join(text.split()) if isinstance(text, str) and text.strip() else None


def listing_changes(snapshot, listing):
    """The surfaces the live listing changed against the snapshot an item was built on, in reading order: 'title',
    'highlight', then 'bullet N' for each bullet that differs (added or dropped bullets included). Text is compared with
    its spacing collapsed. A surface one of the two reads lacks (no highlight, no bullets) is not compared: a missing read
    is not a change."""
    out = [name for name in ('title', 'highlight')
           if _flat(snapshot.get(name)) and _flat(listing.get(name)) and _flat(snapshot.get(name)) != _flat(listing.get(name))]
    before = [_flat(b) for b in snapshot.get('bullets') or []] if isinstance(snapshot.get('bullets'), list) else []
    after = [_flat(b) for b in listing.get('bullets') or []] if isinstance(listing.get('bullets'), list) else []
    if before and after:
        for i in range(max(len(before), len(after))):
            if (before[i] if i < len(before) else None) != (after[i] if i < len(after) else None):
                out.append(f'bullet {i + 1}')
    return out


def close_on_listing_change(item, listing, date, product, cfg=None):
    """The AI's close (launch design 4e, spec 4): a For Growth item Growth picked up or pushed copy for (in_progress or
    copy_pushed) is resolved when the run's listing (listing.json) differs from the item's growth.listing_snapshot in the
    title, the highlight or a bullet. The item (changed in place, and returned) gets status resolved, resolved_on `date`,
    its resolution, a history line naming the changed surfaces and workflow.proof 'listing changed <date>: <surfaces>'.

    `product` (the product file's dict) is updated in place (R5, R12): growth.last_listing_change = `date` (the quiet
    window's clock), a growth.passes entry {pass, produced, resolved_on, stage} (any item closed this way is a resolved
    pass, a flag item too), the next window growth.next_pass (no earlier than + pass_floor_weeks, by +
    pass_ceiling_weeks, config.json's growth block, through growth.due_dates) and growth.candidates cleared: the gate
    starts again on the new copy. An open item never closes on a diff (nobody said they were on it); no listing read, or
    an item without a snapshot, closes nothing."""
    if not isinstance(item, dict) or item.get('kind') != 'growth' or item.get('status') not in CLOSABLE:
        return item
    g_item = item.get('growth') or {}
    snapshot = g_item.get('listing_snapshot')
    if not isinstance(listing, dict) or not isinstance(snapshot, dict):
        return item
    changed = listing_changes(snapshot, listing)
    if not changed:
        return item
    cfg = cfg or config()
    surfaces = ', '.join(changed)
    proof = f'listing changed {date}: {surfaces}'
    read = snapshot.get('read_at') or 'when the block was produced'
    item.update(status='resolved', resolved_on=date, resolution=f'{proof} (the weekly run read the live listing)')
    item['workflow'] = dict(item.get('workflow') or {}, proof=proof)
    item['history'] = list(item.get('history') or []) + [dict(
        date=date, status='resolved', owner=item.get('owner'),
        note=f"Listing change seen on {date} in {surfaces}, against the copy read {read}: the {g_item.get('pass')} is done")]
    g = growth_block(product)
    g['last_listing_change'] = date
    g['passes'] = list(g.get('passes') or []) + [{'pass': g_item.get('pass'), 'produced': g_item.get('produced'),
                                                  'resolved_on': date, 'stage': (g_item.get('stage') or {}).get('name')}]
    g.pop('candidates', None)
    g['next_pass'] = growth.due_dates(product, cfg)['next_pass']
    return item


def growth_run_steps(product, run_dir, asin, date, cfg):
    """What a publish (build_doc) and growth --emit do with a run's For Growth files before the item is read: Growth's
    saved clicks (item_statuses.json) onto the item, then the close on a listing change (listing.json), with an activity
    line when it closes. `product` is changed in place. Returns the close's proof, or None."""
    entries = saved_item_statuses(run_dir, asin)
    if entries is not None and product.get('human_review'):
        product['human_review'] = apply_statuses(product['human_review'], entries)
    item = growth_item(product.get('human_review'))
    if item is None or item.get('status') not in CLOSABLE:
        return None
    close_on_listing_change(item, load_listing(run_dir, asin), date, product, cfg)
    if item['status'] != 'resolved':
        return None
    window = product['growth']['next_pass']
    surfaces = item['workflow']['proof'].split(': ', 1)[1]
    add_activity(product, f"For Growth: listing change seen on {product_name(product, asin)} in {surfaces}, so the "
                          f"{item['growth'].get('pass')} is resolved; next listing pass no earlier than "
                          f"{window['no_earlier_than']}, by {window['by']}")
    return item['workflow']['proof']


def new_flags(old, new):
    """R7: the rotate-out flags (terms) an incoming For Growth item carries that the stored item lacked, in the item's
    order. None when the merge kept the stored block (the same produced); a closed stored item's flags count as none, as
    a new pass starts a new flag list (R11)."""
    if not new:
        return []
    if old and (old.get('growth') or {}).get('produced') == (new.get('growth') or {}).get('produced'):
        return []
    had = set() if not old or growth.closed(old) else {
        f.get('term') for f in (old.get('growth') or {}).get('flags') or [] if isinstance(f, dict)}
    return [f['term'] for f in (new.get('growth') or {}).get('flags') or []
            if isinstance(f, dict) and f.get('term') and f['term'] not in had]


# ---- secrets and HTTP ---------------------------------------------------------------------------------------

def read_secrets():
    out = {}
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    out[k.strip()] = v.strip()
    return out


def sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def readable_password():
    alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
    return '-'.join(''.join(pysecrets.choice(alphabet) for _ in range(5)) for _ in range(4))


def personal_entry(name, tok, role='publisher'):
    """The Railway entry for a personal key, `Name:<sha256>` (the hash only, safe to send), with the variable it goes in:
    PUBLISHERS for a publisher's token, GROWTH_PUBLISHERS for a Growth key (the item status route only), and `line`, the
    entry with where it goes."""
    variable = 'GROWTH_PUBLISHERS' if role == 'growth' else 'PUBLISHERS'
    entry = f'{name}:{sha(tok)}'
    return dict(variable=variable, entry=entry, line=f'{entry}  (add it to the Railway variable {variable})')


def growth_key_path(name):
    """Where a Growth member's key is saved: its own file beside the secrets file, so the issuer's own token stays."""
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return os.path.join(os.path.dirname(SECRETS_FILE), f'growth-{slug}.env')


def issue_growth_key(a):
    """secrets --personal "<Name>" --role growth (launch design 4e): Kim or Lee makes a For Growth key for a Growth
    member. The key goes, with ROLE=growth and the member's name, into its own private file beside the secrets file
    (growth-<name>.env), never into the issuer's own entries and never onto the screen; the output is the
    GROWTH_PUBLISHERS entry (Name:<sha256>) and where the key is. R34: Kim and Lee are approver names (human_review's
    levels), so a Growth key may not carry them: a Growth name must never read as an approval."""
    name = a.personal.strip()
    if not all(ch.isalnum() or ch in ' ._-' for ch in name) or not 0 < len(name) <= 40:
        raise SystemExit('name: letters, digits, spaces, . _ - (up to 40)')
    level = signer_level(name)
    if level != 'owner':
        raise SystemExit(f'"{name}" is an approver name ({level} approves on the dashboard), so a Growth key may not '
                         "carry it: use the Growth member's own name. Nothing written.")
    path = growth_key_path(name)
    if os.path.exists(path) and not a.force:
        raise SystemExit(f'{path} already holds a Growth key for {name}; --force makes a new one (then replace its '
                         'GROWTH_PUBLISHERS entry on Railway)')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = pysecrets.token_urlsafe(32)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('# YourBrand PPC dashboard: a For Growth key. Keep this file private; never commit, zip or paste it.\n'
                f'# Created {dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} for {name}. It only marks '
                'For Growth items "Picked up" and "Copy pushed"; it cannot publish or approve.\n'
                '# Hand the PUBLISH_TOKEN value to them privately (never Slack or a shared doc).\n'
                f'ROLE=growth\nPUBLISHER_NAME={name}\nPUBLISH_TOKEN={key}\n')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    entry = personal_entry(name, key, 'growth')
    print(json.dumps(dict(role='growth', name=name, key_file=path, railway_variable=entry['variable'],
                          entry=entry['entry'], line=entry['line'],
                          note=(f"The key itself is in key_file (PUBLISH_TOKEN), never printed: hand it to {name} "
                                'privately; they paste it once at "Sign in" on a For Growth card. Add the entry (a hash, '
                                f"safe to send) to the Railway variable {entry['variable']}; removing it revokes the "
                                'key.')), indent=1, ensure_ascii=False))


def cmd_secrets(a):
    if (getattr(a, 'role', None) or 'publisher') == 'growth':
        if not a.personal:
            raise SystemExit('--role growth goes with --personal "<Name>", the Growth member the key is for')
        return issue_growth_key(a)
    if a.personal:
        # A teammate's own publish token: created and kept on their laptop; only its hash goes to Railway.
        s = read_secrets()
        if s.get('PUBLISH_TOKEN') and not a.force:
            raise SystemExit(f'{SECRETS_FILE} already has a PUBLISH_TOKEN; use --hashes to get your PUBLISHERS entry, '
                             'or --personal NAME --force to replace it')
        name = a.personal.strip()
        if not all(ch.isalnum() or ch in ' ._-' for ch in name) or not 0 < len(name) <= 40:
            raise SystemExit('name: letters, digits, spaces, . _ - (up to 40)')
        os.makedirs(os.path.dirname(SECRETS_FILE), exist_ok=True)
        keep = [f'{k}={v}' for k, v in s.items() if k not in ('PUBLISH_TOKEN', 'PUBLISHER_NAME')]
        with open(SECRETS_FILE, 'w', encoding='utf-8') as f:
            f.write('# YourBrand PPC dashboard secrets. Keep this file private; never commit or zip it.\n'
                    f'# Personal publish token, created {dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}\n'
                    + ''.join(line + '\n' for line in keep) +
                    f'PUBLISHER_NAME={name}\nPUBLISH_TOKEN={pysecrets.token_urlsafe(32)}\n')
        try:
            os.chmod(SECRETS_FILE, 0o600)
        except OSError:
            pass
        s = read_secrets()
        print(json.dumps(dict(secrets_file=SECRETS_FILE, send_this_to_the_run_owner=f"{name}:{sha(s['PUBLISH_TOKEN'])}",
                              note='It is a hash, safe to send. The run owner adds it to the Railway variable PUBLISHERS.'), indent=1))
        return
    if a.init:
        if os.path.exists(SECRETS_FILE) and not a.force:
            raise SystemExit(f'{SECRETS_FILE} already exists; use --hashes, or --init --force to replace both secrets')
        os.makedirs(os.path.dirname(SECRETS_FILE), exist_ok=True)
        with open(SECRETS_FILE, 'w', encoding='utf-8') as f:
            f.write('# YourBrand PPC dashboard secrets. Keep this file private; never commit or zip it.\n'
                    '# DASHBOARD_PASSWORD is the team password (any user name). PUBLISH_TOKEN lets the skill publish.\n'
                    f'# Created {dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}\n'
                    f'DASHBOARD_PASSWORD={readable_password()}\nPUBLISH_TOKEN={pysecrets.token_urlsafe(32)}\n')
        try:
            os.chmod(SECRETS_FILE, 0o600)
        except OSError:
            pass
    s = read_secrets()
    if not s.get('PUBLISH_TOKEN'):
        raise SystemExit(f'no publish token in {SECRETS_FILE}; run: python dashboard.py secrets --init (run owner) '
                         'or secrets --personal "Your Name" (teammate)')
    out = dict(secrets_file=SECRETS_FILE, railway_variables=dict(PUBLISH_TOKEN_SHA256=sha(s['PUBLISH_TOKEN'])))
    if s.get('DASHBOARD_PASSWORD'):
        out['railway_variables']['DASHBOARD_PASSWORD_SHA256'] = sha(s['DASHBOARD_PASSWORD'])
    out['publishers_entry'] = f"{default_by()}:{sha(s['PUBLISH_TOKEN'])}"
    print(json.dumps(out, indent=1))


def write_secrets(set_values, remove=()):
    """Rewrites the secrets file with some keys set or removed; every other line stays (comments included)."""
    lines = []
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE, encoding='utf-8') as f:
            lines = f.read().splitlines()
    out, done = [], set()
    for line in lines:
        key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else None
        if key in remove:
            continue
        if key in set_values:
            if key in done:
                continue
            out.append(f'{key}={set_values[key]}')
            done.add(key)
        else:
            out.append(line)
    if not lines:
        out.append('# YourBrand PPC dashboard secrets. Keep this file private; never commit or zip it.')
    out += [f'{k}={v}' for k, v in set_values.items() if k not in done]
    os.makedirs(os.path.dirname(SECRETS_FILE), exist_ok=True)
    with open(SECRETS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    try:
        os.chmod(SECRETS_FILE, 0o600)
    except OSError:
        pass


def post_plain(path, body, bearer=None):
    """A JSON POST to the dashboard with no key, or with the given one; returns (status, answer)."""
    url = (config().get('dashboard') or {}).get('url')
    if not url:
        raise SystemExit('config.json dashboard.url is not set')
    headers = {'User-Agent': 'ppc-ai-bidding-audit', 'Accept': 'application/json', 'Content-Type': 'application/json'}
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    req = urllib.request.Request(url.rstrip('/') + path, data=json.dumps(body).encode('utf-8'), method='POST', headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, json.loads((gzip.decompress(raw) if r.headers.get('Content-Encoding') == 'gzip' else raw) or b'{}')
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(gzip.decompress(raw) if e.headers.get('Content-Encoding') == 'gzip' else raw)
        except (ValueError, OSError):
            return e.code, {'error': raw[:300].decode('utf-8', 'replace')}


def cmd_login(a):
    """login: a person signs this laptop in to the dashboard with their own account. They type the email and the password
    themselves, in their own terminal (the password is hidden and never stored); the dashboard answers with a laptop key,
    saved as PUBLISH_TOKEN in the secrets file, so publish, claim, reviews and the rest run as that person. An AI agent
    never runs this for anyone: it would need the password (AGENTS.md rule 5)."""
    import getpass
    import platform
    if not sys.stdin.isatty():
        raise SystemExit('login asks for your password, so run it yourself in a terminal (not through an AI agent): '
                         'python scripts/dashboard.py login')
    if os.environ.get('PPC_DASHBOARD_TOKEN'):
        print('Note: PPC_DASHBOARD_TOKEN is set in this terminal and wins over the saved key; unset it after login.')
    email = (a.email or input('Dashboard email: ')).strip()
    password = getpass.getpass('Dashboard password (hidden as you type): ')
    label = (a.label or f'{getpass.getuser()} on {platform.node()}')[:80]
    status, res = post_plain('/api/auth/login', dict(email=email, password=password, laptop=label))
    password = None
    if status != 200 or not res.get('key'):
        raise SystemExit(f"Not signed in: {res.get('error') or 'HTTP ' + str(status)}")
    user = res['user']
    old = read_secrets()
    keep = {}
    if old.get('PUBLISH_TOKEN') and not old.get('PUBLISH_KEY_ID') and not old.get('PREVIOUS_PUBLISH_TOKEN'):
        keep['PREVIOUS_PUBLISH_TOKEN'] = old['PUBLISH_TOKEN']  # the old key, until LEGACY_KEYS is off; delete it then
    write_secrets(dict(keep, PUBLISHER_NAME=user['name'], PUBLISH_TOKEN=res['key'], PUBLISH_KEY_ID=res['key_id']),
                  remove=('ROLE',))
    print(f"Signed in as {user['name']} ({user['role']}). This laptop's key is saved in {SECRETS_FILE} "
          f"and lasts until {res['expires_at'][:10]}. An admin can end it on the dashboard's Users page.")


def cmd_logout(a):
    """logout: ends this laptop's key on the dashboard and removes it from the secrets file."""
    s = read_secrets()
    if not s.get('PUBLISH_KEY_ID'):
        raise SystemExit(f'{SECRETS_FILE} holds no laptop key (from login); nothing to sign out')
    status, res = post_plain('/api/auth/logout', {}, bearer=s.get('PUBLISH_TOKEN'))
    write_secrets({}, remove=('PUBLISH_TOKEN', 'PUBLISH_KEY_ID'))
    print('Signed out: the key is ended on the dashboard and removed from this laptop.' if status == 200 and res.get('signed_out')
          else 'The key was already ended on the dashboard; it is removed from this laptop.')


def cmd_users(a):
    """users list | users add: the dashboard's accounts, with this laptop's key. While no admin account exists, a personal
    PUBLISHERS key may add the first one (an admin); after that only an admin adds people. A new person's temporary
    password is printed once: send it to them privately."""
    if a.users_cmd == 'add':
        res = call('POST', '/api/users', json.dumps(dict(email=a.email, name=a.name, role=a.role)))
        u = res['user']
        print(f"Added {u['name']} ({u['email']}, {u['role']}). Temporary password: {res['temp_password']}\n"
              f"Send it to {u['name']} privately. They sign in at the dashboard and choose their own.")
        return
    for u in call('GET', '/api/users'):
        state = 'switched off' if u['disabled'] else 'not signed in yet' if u['must_change'] else 'active'
        print(f"{u['name']:<20} {u['email']:<34} {u['role']:<7} {state}")


def default_by():
    """Who is running this: PPC_DASHBOARD_BY, else PUBLISHER_NAME in the secrets file, else 'the run owner'."""
    return os.environ.get('PPC_DASHBOARD_BY') or read_secrets().get('PUBLISHER_NAME') or 'the run owner'


def token():
    t = os.environ.get('PPC_DASHBOARD_TOKEN')
    if not t:
        s = read_secrets()
        if s.get('ROLE') == 'growth':
            raise SystemExit(f'{SECRETS_FILE} holds a For Growth key (ROLE=growth): it only marks For Growth items on the '
                             'dashboard and cannot publish or read with this script. Point PPC_DASHBOARD_SECRETS at your '
                             'own secrets file.')
        t = s.get('PUBLISH_TOKEN')
    if not t:
        raise SystemExit(f'no publish token: set PPC_DASHBOARD_TOKEN or put PUBLISH_TOKEN in {SECRETS_FILE}')
    return t


def call(method, path, body=None, base_version=None):
    url = (config().get('dashboard') or {}).get('url')
    if not url:
        raise SystemExit('config.json dashboard.url is not set')
    headers = {'Authorization': 'Bearer ' + token(), 'User-Agent': 'ppc-ai-bidding-audit', 'Accept': 'application/json'}
    if base_version:
        headers['X-Base-Version'] = base_version
    data = None
    if body is not None:
        data = gzip.compress(body if isinstance(body, bytes) else body.encode('utf-8'))
        headers.update({'Content-Type': 'application/octet-stream', 'Content-Encoding': 'gzip'})
    req = urllib.request.Request(url.rstrip('/') + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                raw = gzip.decompress(raw)
            return json.loads(raw or b'{}')
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            msg = json.loads(gzip.decompress(raw) if e.headers.get('Content-Encoding') == 'gzip' else raw).get('error')
        except (ValueError, OSError, AttributeError):
            msg = raw[:300]
        raise SystemExit(f'{method} {path}: HTTP {e.code}: {msg}')


def product_path(asin, data=None):
    return os.path.join(data_dir(config(), data), 'asins', f'{asin}.json')


def put_page(a, doc, product):
    """Publish a product's page, guarded by the version its product file last saw, then record the new version in
    the product file (commit and push it, so the next person's publish is not refused)."""
    body = json.dumps(doc, ensure_ascii=False, separators=(',', ':'))
    base = None if getattr(a, 'force', False) else ((product.get('dashboard') or {}).get('version') or 'none')
    res = call('PUT', f'/api/products/{doc["asin"]}', body, base_version=base)
    product['dashboard'] = dict(version=res.get('version'), published_at=res.get('published_at'),
                                published_by=res.get('published_by') or doc.get('published_by'))
    with open(product_path(doc['asin'], getattr(a, 'data', None)), 'w', encoding='utf-8') as f:
        json.dump(product, f, indent=1, ensure_ascii=False)
        f.write('\n')
    return res


# ---- commands -------------------------------------------------------------------------------------------------

def cmd_logs(a):
    """Publish the run logs (logs/*.md at the repository root) to the dashboard, where /logs lists them and
    /api/logs/<name> serves each one, so a reader without the repository (a teammate, an LLM) sees the record.
    A file whose SHA-256 matches the dashboard's index is skipped; one activity line sums up a push."""
    if a.list:
        for e in call('GET', '/api/logs'):
            print(f"{str(e.get('updated_at', ''))[:16]}  {e.get('bytes', 0):>7}  {e.get('name')}  ({e.get('by') or 'shared token'})")
        return
    root = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
    patterns = a.push or [os.path.join(root, 'logs', '*.md')]
    paths = sorted({p for pat in patterns for p in glob.glob(pat)})
    if not paths:
        raise SystemExit('no local logs matched ' + ', '.join(patterns))
    live = {e['name']: e for e in call('GET', '/api/logs') if isinstance(e, dict) and e.get('name')}
    pushed, unchanged = [], 0
    for p in paths:
        name = os.path.basename(p)
        with open(p, encoding='utf-8') as f:
            text = f.read()
        if live.get(name, {}).get('sha256') == hashlib.sha256(text.encode('utf-8')).hexdigest():
            unchanged += 1
            continue
        if a.dry_run:
            print('would push', name)
        else:
            res = call('PUT', f'/api/logs/{name}', text)
            print('pushed', name, res.get('bytes'), 'bytes')
        pushed.append(name)
    if pushed and not a.dry_run:
        call('POST', '/api/activity', json.dumps(dict(text=f"published {len(pushed)} run log{'s' if len(pushed) != 1 else ''} to /logs",
                                                      by=a.by or default_by())))
    print(json.dumps(dict(pushed=len(pushed), unchanged=unchanged, dry_run=bool(a.dry_run),
                          url=config()['dashboard']['url'].rstrip('/') + '/logs'), indent=1))


def cmd_publish(a):
    date = a.date or sgt_today()   # the Singapore date: it dates the For Growth close, passes and last_listing_change
    label = a.label or ('Weekly run' if a.state else 'Run')
    doc, product = build_doc(a.asin, a.run, a.state, label, date, a.by, a.data, a.due_plan)
    body = json.dumps(doc, ensure_ascii=False, separators=(',', ':'))
    size = dict(bytes=len(body.encode('utf-8')), gzip_bytes=len(gzip.compress(body.encode('utf-8'))),
                changes=len(doc['run']['changes']), terms=len(doc['terms']['rows']), invest=len(doc['invest']['rows']))
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(body)
    if a.dry_run:
        print(json.dumps(dict(dry_run=True, out=a.out, **size), indent=1))
        return
    if a.state == 'applied':
        product['last_applied'] = dict(date=date, label=label, run=os.path.basename(os.path.normpath(a.run)))
    res = put_page(a, doc, product)
    url = config()['dashboard']['url'].rstrip('/')
    print(json.dumps(dict(res, page=f'{url}/#/{a.asin}', **size), indent=1))


def cmd_review(a):
    path = product_path(a.asin, a.data)
    product = load_json(path)
    if not product:
        raise SystemExit('Missing product file: ' + a.asin)
    product['human_review'] = transition_human_review(product.get('human_review', []), a.id, a.status, a.owner, a.note, sgt_today())
    if not a.dry_run:
        with open(path, 'w', encoding='utf-8') as stream:
            json.dump(product, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
    print(json.dumps(dict(asin=a.asin, dry_run=a.dry_run, human_review=product['human_review'], live_published=False), ensure_ascii=False))


# ---- growth: the For Growth anchor, the switch, and a block by hand ------------------------------------------------------

def cmd_growth(a):
    """The For Growth commands on one product file (never the dashboard, never Amazon): --anchor (the anchor and the next
    listing pass window), --enable / --disable (growth.enabled, with an activity line), --emit (a block by hand from a
    run folder). Each prints what it did; --dry-run writes nothing."""
    cfg = config()
    path = product_path(a.asin, a.data)
    product = load_json(path)
    if product is None:
        raise SystemExit(f'missing product file data/asins/{a.asin}.json')
    if a.emit:
        return growth_emit(a, cfg, path, product)
    if a.anchor:
        return growth_anchor(a, cfg, path, product)
    return growth_switch(a, cfg, path, product, bool(a.enable))


def growth_anchor(a, cfg, path, product):
    """growth --anchor (spec 2): growth.anchor = the later of the Monday launch date (launch_date) and the first ad click
    (--clicks-daily, the run's clicks_daily.json), or the one known; --date YYYY-MM-DD --source hand sets it by hand, and
    a hand-set anchor stays until another --date replaces it. growth.next_pass is written with it (growth.due_dates: both
    dates the first due date before a resolved pass). No anchor to be had stops, writing nothing."""
    if bool(a.source) != bool(a.date):
        raise SystemExit('--date YYYY-MM-DD and --source hand go together: the anchor set by hand. Nothing written.')
    before = (product.get('growth') or {}).get('anchor') if isinstance(product.get('growth'), dict) else None
    if a.date:
        try:
            day = dt.date.fromisoformat(a.date).isoformat()
        except ValueError:
            raise SystemExit(f'--date must be YYYY-MM-DD; got {a.date!r}. Nothing written.')
        new = {'date': day, 'source': 'hand'}
    else:
        rows = since = None
        if a.clicks_daily:
            clicks = load_json(a.clicks_daily)
            held = clicks.get('asin') if isinstance(clicks, dict) else None
            if held != a.asin:
                raise SystemExit(f'{a.clicks_daily} holds the click series for {held!r}, not {a.asin}: pull it again '
                                 '(references/data-pull.md). Nothing written.')
            rows, since = clicks.get('rows'), clicks.get('since')
        new = growth.anchor(product, rows if isinstance(rows, list) else None, since)
        if new is None:
            raise SystemExit(f'{a.asin} has no anchor: no launch_date in its product file and no first ad click '
                             f'{"in " + a.clicks_daily if a.clicks_daily else "(pass --clicks-daily <run>/clicks_daily.json)"}. '
                             'Set one by hand: --anchor --date YYYY-MM-DD --source hand. Nothing written.')
    block = dict(product['growth']) if isinstance(product.get('growth'), dict) else {}
    block['anchor'] = new
    dates = growth.due_dates(dict(product, growth=block), cfg)
    block['next_pass'] = dates['next_pass']
    if not a.dry_run:
        product['growth'] = block
        write_product(path, product)
    out = {'asin': a.asin, 'anchor': new, 'first_due': dates['first_due'], 'next_pass': dates['next_pass'],
           'pass': dates['pass'], 'anchor_before': before, 'dry_run': bool(a.dry_run),
           'written': None if a.dry_run else path}
    if not a.date and isinstance(before, dict) and before.get('source') == 'hand':
        out['note'] = 'the anchor set by hand stays; set another with --date YYYY-MM-DD --source hand'
    print(json.dumps(out, indent=1, ensure_ascii=False))


def auto_enable_growth(product, date, cfg):
    """Kim, 2026-10-29 (decision 166): every AI-owned product hands its new proven SKC keywords to Growth, so a publish
    switches For Growth on for an AI product that is off, unless a person turned it off (growth --disable records
    growth.disabled_on). growth.enabled_on is the publish date, so the first-pass ceiling counts from it and a product
    launched long ago does not fire at once. The weekly run still decides readiness (the data floor and 2 proven SKC
    keywords held for 2 runs). Returns True when it switched the product on."""
    if (product.get('registry') or {}).get('bid_owner') != 'AI':
        return False
    g = growth_block(product)
    if g.get('enabled') is True or g.get('disabled_on'):
        return False
    g['enabled'] = True
    g['enabled_on'] = date
    window = growth_card(product, cfg)['next_pass']
    if window:
        g['next_pass'] = window
    add_activity(product, 'For Growth switched on (every AI product, decision 166): the first listing pass comes when the '
                          'AI bidding audit holds 2 proven SKC keywords the copy does not carry'
                          + (f", by {window['by']} at the latest" if window and window.get('by') else ''))
    return True


def growth_switch(a, cfg, path, product, on):
    """growth --enable / --disable (spec 2): growth.enabled, per product, in Kim's rollout order. Only an enabled
    product's weekly run raises a For Growth item. A change gets an activity line; asking for the state it is already in
    changes nothing."""
    settings = cfg.get('growth') or {}
    block = dict(product['growth']) if isinstance(product.get('growth'), dict) else {}
    was = block.get('enabled', settings.get('enabled_default', False)) is True
    block['enabled'] = on
    if on and not was:
        block['enabled_on'] = a.date or (utc_now() + SGT).strftime('%Y-%m-%d')   # the evidence mode's ceiling counts from it (decision 124)
    if on:
        block.pop('disabled_on', None)
        block.pop('disabled_by', None)
    elif was:   # a person's off stays off: a publish never switches it back on (auto_enable_growth)
        block['disabled_on'] = (utc_now() + SGT).strftime('%Y-%m-%d')
        block['disabled_by'] = a.by or default_by()
    window = growth_card(dict(product, growth=block), cfg)['next_pass']
    if on and window:
        block['next_pass'] = window   # a day-56 window stored before decision 124 is replaced, so the file says what fires
    name, by = product_name(product, a.asin), a.by or default_by()
    if on:
        text = f"For Growth enabled by {by}: the weekly run now raises {name}'s listing passes for Growth"
        if window and window.get('on_evidence'):
            text += ('; the first listing pass comes when the AI bidding audit holds 2 proven SKC keywords the copy '
                     f"does not carry, by {window.get('by') or 'the ceiling'} at the latest")
        elif not window:
            text += '; no anchor yet (dashboard.py growth --anchor)'
        elif window['no_earlier_than'] == window['by'] and not growth.resolved_passes(product):
            text += f"; first listing pass due {window['by']}"
        else:
            text += f"; next listing pass no earlier than {window['no_earlier_than']}, by {window['by']}"
    else:
        text = f'For Growth disabled by {by}: the weekly run raises no listing pass for {name} until it is enabled again'
    changed = was != on
    item = growth_item(product.get('human_review')) if changed and not on else None
    if item is not None and growth.closed(item):
        item = None
    if item is not None:
        text += '; its open For Growth item is dismissed'
    if changed and not a.dry_run:
        product['growth'] = block
        if item is not None:   # open item 51e (2026-10-25): no item left on the tab that no run refreshes or closes
            _set_status(item, 'dismissed', None, f'Dismissed: For Growth disabled by {by}',
                        (utc_now() + SGT).strftime('%Y-%m-%d'))
        add_activity(product, text)
        write_product(path, product)
    print(json.dumps(dict(asin=a.asin, enabled=on, was_enabled=was, changed=changed, next_pass=window,
                          activity=text if changed else None, dry_run=bool(a.dry_run),
                          written=path if changed and not a.dry_run else None), indent=1, ensure_ascii=False))


def growth_emit(a, cfg, path, product):
    """growth --emit (spec 3, trigger manual): a fresh For Growth block by hand, any day, for Lee or Kim.

    As a publish does first, Growth's saved clicks (<run>/item_statuses.json) move the stored item on and a picked-up item
    whose copy changed in the run's listing.json is resolved. Then the item is built from the run's plan.json and
    listing.json (growth.build_item, trigger manual), stamped with the Singapore date and time of the emit (not the run's
    date), its pass tag first or second by the product's resolved passes. Over an item not yet closed it is the same pass:
    the status, who set it and the history are kept (a line is added); over a closed one it is a new pass, born open.
    It is merged into the product file's human_review (human_review.merge, with the product file, so it supersedes
    listing-conversion-gap on an AI product) and written to <run>/growth.json, keeping that file's gate counts (the run's
    own). When the stored block is not older than this one, the merge keeps the stored block and the line says so. One
    line is printed; --dry-run prints it and the block, and writes nothing. It never publishes."""
    if not a.run:
        raise SystemExit('--emit needs --run <run folder>: the block is built from its plan.json and listing.json')
    plan = load_json(os.path.join(a.run, 'plan.json'))
    if not plan:
        raise SystemExit(f'No plan.json in {a.run}')
    held = ((plan.get('summary') or [{}])[0] or {}).get('asin')
    if held != a.asin:
        raise SystemExit(f'{a.run} holds the plan for {held}, not {a.asin}. Nothing written.')
    listing, clicks = load_listing(a.run, a.asin), load_clicks_daily(a.run, a.asin)
    now = utc_now() + SGT
    today, produced = now.strftime('%Y-%m-%d'), now.strftime('%Y-%m-%d %H:%M') + ' SGT'
    by = a.by or default_by()
    growth_run_steps(product, a.run, a.asin, today, cfg)
    block = product['growth'] if isinstance(product.get('growth'), dict) else {}
    stored_anchor = block.get('anchor')
    if isinstance(stored_anchor, dict) and stored_anchor.get('date'):
        the_anchor = stored_anchor
    else:
        rows = (clicks or {}).get('rows')
        the_anchor = growth.anchor(product, rows if isinstance(rows, list) else None, (clicks or {}).get('since'))
    dated = dict(product, growth=dict(block, anchor=the_anchor))
    run_growth = load_json(os.path.join(a.run, 'growth.json')) or {}
    candidates = (run_growth.get('candidates') if isinstance(run_growth.get('candidates'), dict)
                  else block.get('candidates') or {})
    previous = growth_item(product.get('human_review'))
    closed = growth.closed(previous)
    trigger = a.trigger or 'manual'
    # built over the stored item even when it is closed: a dismissal's flags stay held through the hold (R43, R49)
    item = growth.build_item(a.asin, plan, dated, cfg, listing, today, trigger, previous=previous,
                             trigger_reason=f'raised by hand by {by}', candidates=candidates, produced=produced)
    if previous is not None:
        if closed:
            note = f"{item['growth']['pass']} raised by hand by {by}"
        else:
            for field in ('status_by', 'status_at', 'owner'):
                if field in previous:
                    item[field] = copy.deepcopy(previous[field])
            note = f'block produced again by hand by {by}, its status kept'
        item['history'] = copy.deepcopy(previous.get('history') or []) + [
            dict(date=today, status=item['status'], owner=item.get('owner'), note=note)]
    item = validate_human_review([item])[0]
    existing = product.get('human_review') or []
    # merge marks every item it was not handed as not seen by the latest sweep; an emit is not a sweep, so they keep theirs
    seen = {i.get('id'): ('detected_latest_sweep' in i, i.get('detected_latest_sweep')) for i in existing if isinstance(i, dict)}
    merged = merge_human_review(existing, [item], today, product=product)
    for i in merged:
        if i['id'] != growth.GROWTH_ID and i['id'] in seen:
            had, value = seen[i['id']]
            if had:
                i['detected_latest_sweep'] = value
            else:
                i.pop('detected_latest_sweep', None)
    kept = growth_item(merged)['growth'].get('produced') != produced
    g = item['growth']
    outs = sum(1 for r in g.get('swaps') or [] if r.get('out'))
    line = (f"{a.asin} {product_name(product, a.asin)}: For Growth block by hand ({trigger}), {g['pass']}, produced "
            f"{produced}: {len(g.get('weave_in') or [])} to weave in, {outs} to move down or remove, "
            f"{len(g.get('offer') or [])} offer problems; ")
    if not block.get('enabled', (cfg.get('growth') or {}).get('enabled_default', False)):
        line += 'growth.enabled is off (the weekly run raises nothing for it); '
    if kept:
        line += (f"kept the stored block (produced {growth_item(merged)['growth'].get('produced')}, not older than this "
                 'one): nothing merged')
    elif a.dry_run:
        line += 'dry run: nothing written'
    else:
        line += (f'merged into data/asins/{a.asin}.json and written to {os.path.join(a.run, "growth.json")}; '
                 'refresh or publish to show it')
    print(line)
    if a.dry_run:
        print(g['block_md'], end='')
        return
    product['human_review'] = merged
    if not kept:
        doc = dict(growth.block_json(item))
        doc.update(asin=a.asin, item=item, trigger=trigger, trigger_reason=g.get('trigger_reason'), anchor=the_anchor,
                   next_pass=growth.due_dates(dated, cfg)['next_pass'], candidates=candidates)
        write_payload_json(os.path.join(a.run, 'growth.json'), doc, ensure_ascii=False, default=str, indent=1)
    write_product(path, product)


# ---- approvals: the team's per-row decisions become payload files and locks ---------------------------------------

DECISIONS = ('approve', 'decline')
# The rows a --live file can check, and the plan field that holds their id in the account (row_id is never read).
# A Business invest moves its B2B owner keyword's bid (design 2026-10-21-b2b-lane-and-roles 4b), so it is checked like one.
BID_ROW_ID = {'Bid change': 'keyword_id', 'Target bid change': 'target_id', 'SB bid change': 'keyword_id',
              'Business invest': 'keyword_id'}
PAUSE_ROW_ID = {'Pause keyword': 'keyword_id', 'Pause target': 'target_id', 'SB pause keyword': 'keyword_id'}


def bid_row_field(change):
    """The plan field holding a bid row's id in the account: BID_ROW_ID's, except a Sponsored Brands target's bid row (an
    'SB bid change' with a target_id, decision 155), which is checked by its target id."""
    if change.get('type') == 'SB bid change' and change.get('target_id') not in (None, ''):
        return 'target_id'
    if change.get('type') == 'SB bid change' and change.get('theme_id') not in (None, ''):
        return 'theme_id'   # a Sponsored Brands theme target's bid row (decision 156)
    return BID_ROW_ID.get(change.get('type'))
BID_TOLERANCE = 0.005  # a live bid this close to the plan's current bid hasn't moved
NOT_CHECKED = object()  # drift_reason's answer for a row with no live keyword or target id
SGT = dt.timedelta(hours=8)  # the dashboard and its records keep Singapore time
# A bids row's approval_required (human_review.LEVELS: owner < Lee < Kim) is met by a signer of that level or higher.
# Anyone else who signed counts as an owner. Names are compared trimmed and case-insensitively.
SIGNER_RANK = {'kim': LEVELS.index('Kim'), 'lee': LEVELS.index('Lee')}
# <run>/payloads/applied_rows.json, {row_id: {"date": YYYY-MM-DD, "folder": auto|review|approved}}: every row that went
# out, the day it first did and the folder it went out from (C4). Rows recorded before C4 read {row_id: YYYY-MM-DD}, folder
# unknown. Written only by `applied`; approvals reads it so a row is never emitted twice.
APPLIED_ROWS = 'applied_rows.json'
# <run>/payloads/approved_decisions.json, {row_id: {by, on, at}}: the approval behind each row approvals put in approved/,
# which `applied` names on the row's approve lock, and (G1) behind each approved row with no payload (a stop-loss review,
# which a person carries out by hand), which log_invest reads as that person's step-down. It sits outside approved/ so it
# is never taken for a payload file.
APPROVED_RECORD = 'approved_decisions.json'
ROWS_FILE = 'rows.json'  # {payload file: [row_id behind each payload row]}, beside every payload folder's files (plan.py)
APPLY_FOLDERS = ('auto', 'review', 'approved')  # the folders a weekly run may apply; held/ never goes out
OLD_APPLIED = 'applied.json'  # Task 7's record in payloads/approved/: no longer read, and never deleted (N9)
PRUNE_DAYS = 90  # a lock that ended more than this many days ago is dropped whenever decisions are written


def _moment(text):
    """An ISO timestamp as an aware UTC datetime, or None when it is missing or unreadable. A naive time reads as UTC."""
    if not isinstance(text, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


def _number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float('inf') and not isinstance(value, bool) else None


def _money(value):
    return f'${_number(value):.2f}'


def bids_item(plan):
    """The run's one Bids item in plan.json's human_review. Exits when there is none, or more than one."""
    items = [i for i in plan.get('human_review') or [] if isinstance(i, dict) and i.get('kind') == 'bid']
    if len(items) != 1:
        raise SystemExit("This run's plan.json has no bids item to approve rows on (nothing waited for a person, or the run "
                         'was planned before the dashboard held bid rows).' if not items else
                         f"This run's plan.json has {len(items)} bids items; there should be exactly one.")
    return items[0]


def needed_level(row):
    """The approval level a bids row asks for; a row whose level can't be read asks for the highest (the safe side)."""
    level = row.get('approval_required') if isinstance(row, dict) else None
    return level if level in LEVELS else LEVELS[-1]


def latest_decisions(item, entries, check=None, decliners=None):
    """(decided, ignored, held): the latest counting decision on each row of this run's Bids item, the entries that don't
    count, and the approvals that can't count, with why.

    `entries` is GET /api/reviews/<ASIN>: every decision ever made on the product, oldest first. Only a signed entry
    (`by` not empty) for this item (item_id), on one of its rows, with a decision of approve or decline counts; the latest
    per row wins, by its `at` time, or by its place in the list when the times tie or can't be read. `decided` maps
    row_id -> that entry. An approval counts only when `check(entry)` (when given) finds nothing wrong with it (B5: what
    the person saw no longer matches the plan) and its signer is at the row's approval level or above (SIGNER_RANK); a
    declination counts from anyone. E3 (I3): `decliners` ({row_id: who declined it}, for the rows a decline holds) raises
    a row's level to the decliner's (human_review.signer_level), so nobody below the person who said no can say yes: "needs
    Lee's approval: Lee declined it (approved by Sam)". F: the same rule holds inside this item. A later approval
    replaces an earlier decline on the row only when its signer ranks at least as high as the decliner (Kim > Lee >
    owner; signer_level) and meets the row's level too; below that the decline stands and the approval is held: "declined
    by Lee; needs Lee's approval to change it (approved by Sam)". A later decline, from anyone, replaces an earlier
    approval. G2 (N2): the decline that sets that bar is the highest-ranked one since the last approval that counted: a
    later decline replaces an earlier decline only when its signer ranks at least as high, so a second, lower "no" never
    lets the lower signer's "yes" through (and the decline lock names the higher decliner). An approval that can't count
    is not a decision: it neither replaces an earlier decision nor is replaced by one, and `held` maps row_id -> (it, why)
    for the rows left with no decision at all, plus the rows a decline made on this item still holds against a later
    approval (the last such approval, and only until a decision after it settles the row).
    `ignored` groups the rest by (item, reason) with a count, and names the rows only for this item's own."""
    rows = {r['row_id']: needed_level(r) for r in item.get('rows') or [] if isinstance(r, dict) and isinstance(r.get('row_id'), str)}
    decliners = decliners or {}
    decided, stamp, groups, held, overruled = {}, {}, {}, {}, {}

    def ignore(entry, reason):
        entry = entry if isinstance(entry, dict) else {}
        item_id = entry.get('item_id') if isinstance(entry.get('item_id'), str) else None
        group = groups.setdefault((item_id, reason), dict(item_id=item_id, reason=reason, count=0, row_ids=set()))
        group['count'] += 1
        if isinstance(entry.get('row_id'), str):
            group['row_ids'].add(entry['row_id'])

    for e in entries:
        if not isinstance(e, dict):
            ignore(e, 'not a decision entry')
        elif e.get('item_id') != item['id']:
            ignore(e, f"decided on another item, not this run's {item['id']}")
        elif not isinstance(e.get('row_id'), str) or e['row_id'] not in rows:
            ignore(e, "the row isn't in this run's bids item")
        elif e.get('decision') not in DECISIONS:
            ignore(e, f"unknown decision {e.get('decision')!r}")
        elif not isinstance(e.get('by'), str) or not e['by'].strip():
            ignore(e, 'unsigned decision')
        else:
            rid, at = e['row_id'], _moment(e.get('at'))
            older = bool(rid in decided and at and stamp.get(rid) and at < stamp[rid])  # listed after a newer decision
            if e['decision'] == 'approve':
                why = check(e) if check else None
                declined = signer_level(decliners.get(rid)) if rid in decliners else None
                level = max(rows[rid], declined or rows[rid], key=LEVELS.index)
                # F: a decline already standing on this row from this item: the approval must rank as high as its decliner
                standing = decided[rid] if rid in decided and decided[rid]['decision'] == 'decline' and not older else None
                if standing is not None:
                    level = max(level, signer_level(standing['by']), key=LEVELS.index)
                if why is None and signer_rank(e['by']) < LEVELS.index(level):
                    if standing is not None:
                        # G2: name the decliner whose rank sets the bar (the plan's earlier, higher decliner, if any)
                        named = standing['by'].strip()
                        if (declined and isinstance(decliners.get(rid), str) and decliners[rid].strip()
                                and LEVELS.index(declined) > LEVELS.index(signer_level(named))):
                            named = decliners[rid].strip()
                        overruled[rid] = (e, f"declined by {named}; needs {level}'s approval to change it "
                                             f"(approved by {e['by'].strip()})")
                        continue  # the decline stands: this approval is no decision
                    who = decliners[rid].strip() if isinstance(decliners.get(rid), str) else None
                    raised = declined not in (None, 'owner') and LEVELS.index(declined) >= LEVELS.index(rows[rid])
                    why = (f"needs {level}'s approval: {who} declined it (approved by {e['by'].strip()})" if raised and who
                           else f"needs {level}'s approval (approved by {e['by'].strip()})")
                if why:
                    held[rid] = (e, why)
                    continue
            if older:
                continue  # an older decision listed after a newer one
            standing = decided.get(rid)
            if (e['decision'] == 'decline' and standing is not None and standing['decision'] == 'decline'
                    and LEVELS.index(signer_level(e['by'])) < LEVELS.index(signer_level(standing['by']))):
                # G2 (N2): a later, lower-ranked decline never lowers the bar. The earlier, higher decline stays the row's
                # decision (its lock names that decliner); a held approval before this decline is stale all the same
                overruled.pop(rid, None)
                stamp[rid] = at or stamp.get(rid)
                continue
            decided[rid] = e
            overruled.pop(rid, None)  # a decision after a held approval settles the row: that approval is stale
            stamp[rid] = at or stamp.get(rid)
    held = {rid: e for rid, e in held.items() if rid not in decided}
    held.update(overruled)  # each is on a row whose standing decision is the decline that held it back
    ignored = []
    for (item_id, reason), g in sorted(groups.items(), key=lambda kv: (kv[0][0] or '', kv[0][1])):
        entry = dict(item_id=g['item_id'], reason=reason, count=g['count'])
        if item_id == item['id']:
            entry['row_ids'] = sorted(g['row_ids'])
        ignored.append(entry)
    return decided, ignored, held


def signer_rank(by):
    """The approval level a signer holds, as an index into LEVELS: Kim and Lee by name, anyone else an owner."""
    return SIGNER_RANK.get(by.strip().lower(), 0)


def live_by_id(live):
    """{keyword, target or theme id as a string: live row} from MAP list_resources rows (keywordId, targetId or themeId)."""
    out = {}
    for row in live:
        for key in ('keywordId', 'targetId', 'themeId'):
            if isinstance(row, dict) and row.get(key) not in (None, ''):
                out[str(row[key])] = row
                break
    return out


DAYPART_SWITCH = 'dayparting switch since the plan'  # drift_reason's opening words for an expected Scale Insights move


def plan_factor(plan):
    """The dayparting modifier the plan read its live bids under (summary inventory.daypart.factor; 1.0 when none). Under a
    modifier the plan's `current` is the base bid (decision 150), and Amazon showed current x factor."""
    summary = (plan.get('summary') or [{}])[0] if isinstance(plan, dict) else {}
    factor = (((summary or {}).get('inventory') or {}).get('daypart') or {}).get('factor')
    return float(factor) if isinstance(factor, (int, float)) and factor > 0 else 1.0


def drift_reason(change, live, mods=None, factor=1.0):
    """Why a row can't go out against the account as it is now, in words; None when it still fits the plan;
    NOT_CHECKED for a row with no live keyword or target id (campaign creations, negatives, budgets).

    `live` is live_by_id's map. The comparison is with the plan's `current`, never with the payload. A bid that moved by
    a dayparting modifier (`mods`: config.json write_window's, plus the factor the rows show, daypart_base.common_factor;
    live = current x m, or current = live x m) still
    can't go out, because the row was priced from the other side of the switch, but its reason opens with DAYPART_SWITCH:
    it is expected, and the fix is to plan again from a fresh read, not to stop or ask (decision 152). `factor` is the
    modifier the plan read under (plan_factor): a live bid still at current x factor has not moved. A move from one
    modifier to another (Kim, 2026-10-26: 0.75 to 0.6, or 0.6 to 0.75) is a dayparting switch too: the live bid is the
    base x the new modifier, and `mods` carries the factors the bids show (daypart_base.common_factor)."""
    kind = change.get('type')
    field = bid_row_field(change) or PAUSE_ROW_ID.get(kind)
    if field is None or change.get(field) in (None, '', 'None'):
        return NOT_CHECKED
    row = live.get(str(change[field]))
    if row is None:
        return 'not found live'
    state = str(row.get('state') or '').lower()
    if kind in PAUSE_ROW_ID:
        return {'paused': 'already paused', 'archived': 'already archived'}.get(state)
    # a paused row (decision 155: a paused keyword or target priced cut only) is checked against its paused live row
    if state and state != 'enabled' and not (change.get('paused') and state == 'paused'):
        return f"no longer enabled live (state {row['state']})"
    planned, now = _number(change.get('current')), _number(row.get('bid'))
    if planned is None:
        return 'the plan has no current bid to check against'
    if now is None:
        return "the live bid can't be read"
    if not round(abs(planned - now), 6) <= BID_TOLERANCE:
        if factor != 1.0 and abs(round(planned * factor, 2) - now) <= daypart_base.TOL:
            return None  # still the bid the plan read: its base under the plan's own modifier
        if daypart_base.switch_moved(planned, now, daypart_base.modifiers(config()) if mods is None else mods):
            return (f"{DAYPART_SWITCH}: planned from {_money(planned)}, now {_money(now)} (Scale Insights' hours modifier "
                    'went on or off, as expected); plan again from a fresh read')
        return f'changed since the plan: planned from {_money(planned)}, now {_money(now)}'
    return None


# What a decision says the person saw on the row (dashboard server, B5): the bids, and (E2, I2) the budgets, the
# top-of-search boosts and a promotion's modelled monthly spend the Bids card shows. Keep it in step with server.ts and
# bids-ui.js (test_bids_ui.mjs checks all three).
SEEN_KEYS = ('current', 'new', 'new_capped', 'budget_now', 'budget', 'tos_now', 'tos', 'modelled_spend_month')
PERCENT_SEEN = ('tos_now', 'tos')  # compared to the whole percent; every other key is money, compared to the cent
SEEN_LABELS = {'budget_now': 'live budget', 'budget': 'budget', 'tos_now': 'live top of search', 'tos': 'top of search',
               'modelled_spend_month': 'monthly spend'}
# C1: an approval counts only when it says what the person saw. Today's client sends no `seen`; the 6b buttons will.
NO_SEEN = "can't confirm what was approved (the decision doesn't say what the person saw)"


def _cents(value):
    """A bid as whole cents, None for None, and False for anything that isn't a number."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) == float('inf'):
        return False
    return round(value * 100)


def _seen_value(key, value):
    """One shown number as it is compared: money in whole cents, a boost in whole percent; None for None, False for
    anything that isn't a number."""
    cents = _cents(value)
    if key in PERCENT_SEEN and cents not in (None, False):
        return round(value)
    return cents


def shown(row):
    """A bids row's numbers as the dashboard shows them, and as an approval must have seen them: SEEN_KEYS in order, money
    in cents and boosts in whole percent (None where the row has none). A business invest row's top of search and budget
    are its campaign's (human_review.card_money: campaign_tos, campaign_budget, what its campaign update writes; spec 9b,
    ruling 19), read the same way from the plan's change row as the card shows them, so the two sides agree."""
    row = dict(row, **card_money(row))
    return tuple(_seen_value(k, row.get(k)) for k in SEEN_KEYS)


def read_seen(seen):
    """A decision's `seen` as shown() gives it, or None when it can't be read (not a dict of SEEN_KEYS, each a number or
    null). A key it leaves out reads as null, so it matches only a row that has none (E2: an older client's seen, which
    names only the bids, can't confirm a budget)."""
    if not isinstance(seen, dict) or any(k not in SEEN_KEYS for k in seen):
        return None
    out = tuple(_seen_value(k, seen.get(k)) for k in SEEN_KEYS)
    return None if any(v is False for v in out) else out


def _bid_text(cents):
    return 'none' if cents is None else f'${cents / 100:.2f}'


def _move_text(cents):
    """'$0.30 → $0.37' for (current, new, new_capped) in cents: the bid that is written, the cap when there is one."""
    current, new, capped = cents[:3]
    return f'{_bid_text(current)} → {_bid_text(capped if capped is not None else new)}'


def _seen_text(key, value):
    if value is None:
        return 'none'
    if key in PERCENT_SEEN:
        return f'{value:g}%'
    return f"${value / 100:.2f}{'/month' if key == 'modelled_spend_month' else '/day'}"


def _moved_text(saw, now):
    """(what was seen, what the plan says now), naming only what moved: the bid move as before, then each budget, boost or
    monthly spend that moved ('budget $15.00/day')."""
    a, b = [], []
    if saw[:3] != now[:3]:
        a.append(_move_text(saw))
        b.append(_move_text(now))
    for i, key in enumerate(SEEN_KEYS[3:], 3):
        if saw[i] != now[i]:
            a.append(f'{SEEN_LABELS[key]} {_seen_text(key, saw[i])}')
            b.append(f'{SEEN_LABELS[key]} {_seen_text(key, now[i])}')
    return ', '.join(a), ', '.join(b)


def seen_check(item, rows):
    """The C1 test of an approval, as latest_decisions' `check`: why it can't count, or None.

    An approval counts only when it carries `seen` and that matches the row in the run's plan.json (`rows`, its change rows
    by row_id; else the plan's own bids item row) on every SEEN_KEYS number: the bids, budgets and monthly spend to the
    cent, the boosts to the whole percent (E2). Else "re-planned since it was approved (saw ..., now ...)", naming what moved.
    One without `seen` never counts (NO_SEEN). The product file's copy of the item is never read: a re-publish or a
    compaction changes it, and plan.json is what goes out."""
    item_rows = {r['row_id']: r for r in item.get('rows') or [] if isinstance(r, dict) and isinstance(r.get('row_id'), str)}

    def check(entry):
        if entry.get('seen') is None:
            return NO_SEEN
        saw = read_seen(entry['seen'])
        if saw is None:
            return "can't read what was seen when it was approved"
        now = shown(rows.get(entry['row_id']) or item_rows.get(entry['row_id']) or {})
        if saw != now:
            was, is_now = _moved_text(saw, now)
            return f're-planned since it was approved (saw {was}, now {is_now})'
        return None
    return check


REAPPROVABLE_TYPES = lanes.DIRECTION_BID_TYPES + lanes.DIRECTION_PAUSE_TYPES  # B9, as C3 limits it: bid and pause rows


def created_searches(product, applied, by_id, today):
    """C3: {creation key: the day it went out} for every search whose creation went out: from the product file's create
    locks (kind 'create', written by `applied`) that still hold on `today`, and from this run's own applied rows (by
    search, whatever row id carried them). A day that can't be read reads 'an earlier run'."""
    days = {}

    def note(key, day):
        if key is not None:
            days.setdefault(key, []).append(day if _iso_day(day) else None)
    for d in (product or {}).get('decisions') or []:
        if not isinstance(d, dict) or d.get('kind') != 'create':
            continue
        end = lanes.lock_date(d.get('until')) if isinstance(d.get('until'), str) else None
        if end is not None and end < today:
            continue  # run out: the search is planned (and approved) as any other
        note(plan_lanes.creation_key(str(d.get('id')).partition(':')[0], plan_lanes.created_search(d), d.get('owner_kind')),
             d.get('created_on') if _iso_day(d.get('created_on')) else d.get('on'))
    for rid, day in applied.items():
        c = by_id.get(rid) or {}
        note(plan_lanes.creation_key(c.get('type'), c.get('keyword'), c.get('owner_kind')), day)
    return {key: min((d for d in found if d), default='an earlier run') for key, found in days.items()}


SB_BUILD_TYPE = 'New SB video campaign'  # one build spec per campaign: the campaign, its ad group, video ad and keywords
EXPERIMENT_HELD = 'a rank experiment holds this search until its review'  # G5 (m2): as the Bids card withholds Approve


def _sb_campaign(c):
    """The campaign a Sponsored Brands video creation row builds, by name; None for any other row."""
    name = c.get('campaign') if isinstance(c, dict) and c.get('type') == SB_BUILD_TYPE else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def built_sb_campaigns(product, applied, by_id, today):
    """G3 (N3): {Sponsored Brands video campaign name: the day it was created} for every SB video build that went out,
    whole or in part: from the product file's create locks on SB video rows that carry the campaign (`applied` writes
    them) and still hold on `today`, and from this run's own applied rows ({row_id: date}). A build is created once: any
    other keyword of a campaign named here is added to it by hand, never by handing the build out again."""
    days = {}
    for d in (product or {}).get('decisions') or []:
        if not isinstance(d, dict) or d.get('kind') != 'create' or str(d.get('id')).partition(':')[0] != SB_BUILD_TYPE:
            continue
        name = d['campaign'].strip() if isinstance(d.get('campaign'), str) and d['campaign'].strip() else None
        end = lanes.lock_date(d.get('until')) if isinstance(d.get('until'), str) else None
        if name is None or (end is not None and end < today):
            continue
        days.setdefault(name, []).append(next((v for v in (d.get('created_on'), d.get('on')) if _iso_day(v)), None))
    for rid, day in (applied or {}).items():
        name = _sb_campaign(by_id.get(rid))
        if name is not None:
            days.setdefault(name, []).append(day if _iso_day(day) else None)
    return {name: min((d for d in found if d), default='an earlier run') for name, found in days.items()}


def sb_builds(row_ids, in_folder, by_id):
    """G3: {campaign name: the row ids of its build in the folder (`in_folder`, rows.json order)}, for each Sponsored
    Brands video build a row of `row_ids` belongs to."""
    names = {_sb_campaign(by_id.get(rid)) for rid in row_ids} - {None}
    return {name: [rid for rid in in_folder if _sb_campaign(by_id.get(rid)) == name] for name in sorted(names)}


def held_row_text(c):
    """Why an approved row a lock holds can't go out again (B9 covers bid and pause rows only, C3)."""
    did = {'decline': 'declined', 'approve': 'approved', 'experiment': 'a rank experiment'}.get(c.get('decision'), 'decided')
    who = f" by {c['decided_by']}" if c.get('decided_by') and c.get('decision') != 'experiment' else ''
    on = f" on {c['decided_on']}" if c.get('decided_on') else ''
    return (f"held by an earlier decision ({did}{who}{on}) until {c.get('locked_until')}: only a bid or pause row can be "
            'approved again while it is held')


def evaluate(plan, entries, live, shared, asin, applied=None, product=None, today=None):
    """Everything approvals works out from the plan, the server's decisions and (optionally) the live rows, as a dict:
    files ({payload file: rows}), row_ids ({payload file: [row_id behind each payload row]}, the folder's rows.json),
    skipped ([{row_id, reason}]), ignored, decided ({row_id: entry}), order (the item's row_ids), approved_rows (the plan
    rows that go out, payload or not), no_payload, not_checked, capped ([{row_id, proposed, applied}]), rows ({row_id: plan
    row}), agreed_held (shadow monitor rows approved: an agreement to keep holding, never a payload or a lock) and
    unlocked (approved rows held back, on which an earlier decline's lock is released).

    `applied` is {row_id: date} from the run's payloads/applied_rows.json (what already went out), or None. An approval
    counts only when its `seen` matches the plan row (seen_check, C1). `product` is the product file, for its create locks.
    `today` (a date, Singapore) says which of its create locks still hold (C3). Until 2026-10-22 (B1) an approved promotion
    that took the product past Kim's monthly level was held unless Kim signed it; decision 99 made that level a guide,
    not a gate, so no approval is held for money.

    C3: an approved creation (a new or reused exact campaign, a new Sponsored Brands video campaign) whose search was
    already created, in this run (applied_rows.json) or an earlier one (a create lock), is skipped with its bundle:
    "already created on <date>; nothing to do". A locked row (locked_until) approved again goes out only when it is a bid
    or pause row (B9 as C3 limits it); any other is read-only, and a bundle with a part that can't go out sends nothing.
    G3 (N3): a keyword of a Sponsored Brands video campaign whose build already went out, whole or in part
    (built_sb_campaigns), is skipped: "its campaign <name> was created on <date>; add the keyword to it by hand". G5 (m2):
    a row a rank experiment holds (the plan's decision, or the item row's lock_decision, 'experiment') is never approved:
    EXPERIMENT_HELD, as the Bids card withholds Approve.

    The payloads are built from the plan's own change rows by plan.payload_files, so their shapes are the run's own
    (a payload row carries no row_id, so the files themselves can't be filtered by decision). A promotion's bundle goes
    out whole or not at all: only when its promotion and every one of its rows on the item are approved, and none of it
    has been applied. A bundle nobody has decided a row of is still waiting, like any undecided row, so it isn't
    reported as skipped."""
    applied = applied or {}
    item = bids_item(plan)
    order = [r['row_id'] for r in item['rows'] if isinstance(r, dict) and isinstance(r.get('row_id'), str)]
    changes = plan.get('changes') or []
    by_id = {c.get('row_id'): c for c in changes}
    # E3: a row a decline holds is approved again only at the decliner's level too (the plan change says who declined)
    decliners = {c.get('row_id'): c.get('decided_by') for c in changes if c.get('locked_until') and c.get('decision') == 'decline'}
    decided, ignored, held = latest_decisions(item, entries, seen_check(item, by_id), decliners)
    approved = {rid for rid, e in decided.items() if e['decision'] == 'approve'}
    on_item = set(order)
    skipped = {}  # row_id -> why, first reason wins
    for rid, (_, why) in held.items():
        skipped[rid] = why
    for rid in order:
        if rid in approved and rid in applied:
            skipped.setdefault(rid, f'already applied on {applied[rid]}')
    members, _ = plan_lanes.bundles(changes)
    for i, group in members.items():
        promotion = changes[i]
        parts = [promotion] + group
        shown = [x['row_id'] for x in parts if x.get('row_id') in on_item]
        done = next((applied[x['row_id']] for x in parts if x.get('row_id') in applied), None)
        whole = promotion.get('row_id') in approved and all(rid in approved for rid in shown)
        if done is not None:
            for rid in shown:
                if rid in approved:  # an undecided row of it is simply not going anywhere: nothing to report
                    skipped.setdefault(rid, f"part of a promotion already applied on {done}: {promotion.get('keyword')}")
        elif any(rid in decided or rid in held for rid in shown) and not whole:
            for rid in shown:
                skipped.setdefault(rid, f"part of a promotion that isn't fully approved: {promotion.get('keyword')}")
    # C3: a search's creation that already went out is never emitted again, bundle and all; and a locked row approved
    # again goes out only when it is a bid or pause row (B9). `frozen` rows release no decline: the approval can't stand.
    today = today or dt.date.today()
    created = created_searches(product, applied, by_id, today)
    frozen = set()
    # G3 (N3): a Sponsored Brands video build is created once. A keyword of a campaign whose build already went out (whole
    # or in part) is added to that campaign by hand: handing it out again would make the campaign, its ad group and its
    # video ad a second time
    built = built_sb_campaigns(product, applied, by_id, today)
    for rid in order:
        name = _sb_campaign(by_id.get(rid))
        if rid in approved and name in built:
            skipped.setdefault(rid, f'its campaign {name} was created on {built[name]}; add the keyword to it by hand (the '
                                    'build is never handed out again)')
            frozen.add(rid)
    for i, c in enumerate(changes):
        key = plan_lanes.creation_key(c.get('type'), c.get('keyword'), c.get('owner_kind'))
        if key not in created or c.get('row_id') not in approved:
            continue
        skipped.setdefault(c['row_id'], f'already created on {created[key]}; nothing to do')
        frozen.add(c['row_id'])
        for m in members.get(i, []):
            if m.get('row_id') in approved:
                skipped.setdefault(m['row_id'], f"part of a promotion already created on {created[key]}: {c.get('keyword')}; "
                                                'nothing to do')
                frozen.add(m['row_id'])
    item_rows = {r['row_id']: r for r in item['rows'] if isinstance(r, dict) and isinstance(r.get('row_id'), str)}
    for rid in order:
        c, row = by_id.get(rid) or {}, item_rows.get(rid) or {}
        scope_problem = ownership_scope.reason(c, product, changes) or c.get('ownership_scope_blocked')
        if rid in approved and scope_problem:
            skipped.setdefault(rid, scope_problem)
            frozen.add(rid)
        # G5 (m2): a row a rank experiment holds is never approved, even through the API (the card offers no Approve)
        if rid in approved and ((c.get('locked_until') and c.get('decision') == 'experiment')
                                or (row.get('locked_until') and row.get('lock_decision') == 'experiment')):
            skipped.setdefault(rid, EXPERIMENT_HELD)
            frozen.add(rid)
        if rid in approved and c.get('locked_until') and c.get('type') not in REAPPROVABLE_TYPES:
            skipped.setdefault(rid, held_row_text(c))
            frozen.add(rid)
    for i, group in members.items():
        parts = [x.get('row_id') for x in [changes[i]] + group if x.get('row_id') in on_item]
        if any(rid in frozen for rid in parts):
            for rid in parts:
                if rid in approved:
                    skipped.setdefault(rid, f"part of a promotion that can't go out: {changes[i].get('keyword')}")
                    frozen.add(rid)
    # B6: in a shadow run, approving a row the planner holds (monitor) agrees with holding it: nothing goes out
    summary = (plan.get('summary') or [{}])[0]
    shadow = summary.get('shadow') is not False
    live_ids = None if live is None else live_by_id(live)
    mods = daypart_base.modifiers(shared)
    if live_ids is not None:
        pairs = []
        for rid in order:
            change = by_id.get(rid) or {}
            field = bid_row_field(change)
            row = live_ids.get(str(change.get(field))) if field else None
            if row is not None and _number(change.get('current')) is not None and _number(row.get('bid')) is not None:
                pairs.append((_number(change.get('current')), _number(row.get('bid'))))
        mods = daypart_base.common_factor(pairs, mods)
    going, sendable, no_payload, capped, not_checked, agreed_held = [], [], [], [], {}, []
    for rid in order:
        if rid not in approved or rid in skipped:
            continue
        change = by_id.get(rid)
        if change is None:
            skipped[rid] = "the row isn't in this run's plan"
        elif shadow and change.get('lane') == 'monitor':
            agreed_held.append(rid)
        elif not payload_files([as_written(change)], shared, asin):
            going.append(change)  # approved, but a person does it (a stop-loss review, a setting in Scale Insights)
            no_payload.append(dict(row_id=rid, type=change.get('type')))
        else:
            why = None if live_ids is None else drift_reason(change, live_ids, mods, plan_factor(plan))
            if why is NOT_CHECKED:
                not_checked[change.get('type')] = not_checked.get(change.get('type'), 0) + 1
            elif why:
                skipped[rid] = why
                continue
            going.append(change)
            sendable.append(as_written(change))
            if change.get('new_capped') is not None and change['new_capped'] != change.get('new'):
                capped.append(dict(row_id=rid, proposed=change.get('new'), applied=change['new_capped']))
    going_ids = {c.get('row_id') for c in going}
    return dict(files=dict(payload_files(sendable, shared, asin)), row_ids=payload_row_ids(sendable, shared, asin),
                skipped=[dict(row_id=rid, reason=skipped[rid]) for rid in order if rid in skipped],
                ignored=ignored, decided=decided, order=order, approved_rows=going, no_payload=no_payload,
                not_checked=not_checked, capped=capped, rows=by_id, agreed_held=agreed_held,
                unlocked=[rid for rid in order if rid in approved and rid not in going_ids and rid not in applied
                          and rid not in agreed_held and rid not in frozen])


def approved_payloads(plan, decisions, live, shared, asin, applied=None):
    """({payload file name: rows}, skipped): what the team approved on this run's Bids item, ready for MAP.

    `decisions` is the server's list (GET /api/reviews/<ASIN>); `live` the live rows to check for drift, or None;
    `shared` is config.json; `applied` ({row_id: date}) what already went out, or None. `skipped` lists {row_id, reason}
    for approved rows held back: an approval that doesn't say what the person saw, numbers that moved since they saw
    them, a signer below the row's approval level, a promotion that isn't fully approved, a bid or state that changed
    since the plan, a row already applied. See `evaluate` for the details."""
    result = evaluate(plan, decisions, live, shared, asin, applied)
    return result['files'], result['skipped']


def read_live(path):
    """The live rows in a --live file: MAP list_resources output saved as a list, as {"data": [...]}, {"results": [...]}
    or {"items": [...]}, or in the tool-result wrapper Claude Code saves big outputs in."""
    try:
        with open(path, encoding='utf-8') as f:
            obj = json.load(f)
        if isinstance(obj, list) and obj and isinstance(obj[0], dict) and 'text' in obj[0] and 'type' in obj[0]:
            obj = json.loads(obj[0]['text'])
    except (OSError, ValueError) as e:
        raise SystemExit(f"can't read the --live file {path}: {e}")
    rows = obj if isinstance(obj, list) else next(
        (obj[k] for k in ('data', 'results', 'items') if isinstance(obj, dict) and isinstance(obj.get(k), list)), None)
    if rows is None or not all(isinstance(r, dict) for r in rows):
        raise SystemExit(f'the --live file {path} must hold a list of live rows (each with keywordId or targetId, bid and/or '
                         'state), or {"data": [...]} / {"results": [...]} / {"items": [...]}')
    return rows


def _iso_day(value):
    """A YYYY-MM-DD string as a date, or None."""
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _applied_entry(value):
    """One applied_rows.json value as {date, folder}, or None when it can't be read. The older {row_id: date} shape reads as
    folder None (unknown)."""
    if isinstance(value, str):
        return dict(date=value, folder=None) if _iso_day(value) else None
    if (isinstance(value, dict) and set(value) == {'date', 'folder'} and _iso_day(value['date'])
            and value['folder'] in APPLY_FOLDERS):
        return dict(value)
    return None


def read_applied_raw(path):
    """The run's payloads/applied_rows.json as written ({} when there is none), checked: every value is {date, folder} or
    the older date. An unreadable one stops the command, because what already went out can't be known."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            obj = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"can't read {path}: {e}. Nothing written.")
    if not isinstance(obj, dict) or not all(isinstance(k, str) and _applied_entry(v) for k, v in obj.items()):
        raise SystemExit(f'{path} must be {{"<row_id>": {{"date": "YYYY-MM-DD", "folder": "auto|review|approved"}}, ...}} (or the '
                         'older {"<row_id>": "YYYY-MM-DD"}): the rows that went out, the day each first did and from which '
                         'folder. Nothing written.')
    return obj


def read_applied_record(path):
    """{row_id: {date, folder}} from the run's payloads/applied_rows.json (`applied` writes it when a payload folder went
    out); folder is None for a row recorded before C4. {} when there is no such file."""
    return {rid: _applied_entry(v) for rid, v in read_applied_raw(path).items()}


def read_applied(path):
    """{row_id: YYYY-MM-DD}: the rows of the run's payloads/applied_rows.json and the day each first went out."""
    return {rid: e['date'] for rid, e in read_applied_record(path).items()}


def saved_review_entries(path):
    """The decisions in a run's saved reviews.json (`dashboard.py reviews --save`): its `entries`, or the older bare list;
    [] when there is none. One that can't be read stops the command."""
    if not os.path.exists(path):
        return []
    try:
        obj = load_json(path)
    except (OSError, ValueError) as e:
        raise SystemExit(f"can't read {path}: {e}. Nothing recorded.")
    entries = obj.get('entries') if isinstance(obj, dict) else obj
    if not isinstance(entries, list):
        raise SystemExit(f"{path} holds no list of decisions, so it can't be checked. Nothing recorded.")
    return entries


def read_rows_file(path):
    """{payload file: [row_id, ...]} from a payload folder's rows.json; stops the command when it can't be read."""
    try:
        with open(path, encoding='utf-8') as f:
            obj = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"can't read {path}: {e}. Nothing written.")
    if not isinstance(obj, dict) or not all(isinstance(k, str) and isinstance(v, list) and all(isinstance(i, str) for i in v)
                                            for k, v in obj.items()):
        raise SystemExit(f'{path} must be {{"<payload file>": ["<row_id>", ...]}}. Nothing written.')
    return obj


def unreconciled_approved(folder, applied):
    """What payloads/approved/ handed out for an apply that payloads/applied_rows.json doesn't record (C2): the row_ids
    its rows.json names and `applied` lacks, in order, plus '<file> (no rows.json)' for each payload file of a folder with
    no rows.json (what such a folder handed out can't be told). Task 7's applied.json is not a payload. An empty list
    when the folder holds nothing unreconciled."""
    rows_path = os.path.join(folder, ROWS_FILE)
    if os.path.exists(rows_path):
        ids = dict.fromkeys(rid for v in read_rows_file(rows_path).values() for rid in v)
        return [rid for rid in ids if rid not in applied]
    return [f'{os.path.basename(p)} (no rows.json)' for p in sorted(glob.glob(os.path.join(glob.escape(folder), '*.json')))
            if os.path.basename(p) != OLD_APPLIED]


REVIEW_DECIDED = 'this run is being decided row by row; apply approved/ instead'


def check_review_route(asin, run, plan, product, shared, row_ids, day):
    """C4: payloads/review/ (the preview's whole-run yes) may go out only while nobody decides the run row by row. Stops the
    command when the run's bids item has any decision, on the dashboard or in <run>/reviews.json, or when a row of
    review/ is held by a decline on the dashboard (on any item, made after the plan). Its locks are built as the planner
    builds them (plan_lanes.lock_table over the product file's decisions and the dashboard's), so a decline step 2 already
    settled keeps the direction it was written with: a declined raise that this plan re-planned as a cut holds nothing
    (N-new-3), while a decline made after the plan holds the row whichever way it moves. One read of the dashboard."""
    entries = call('GET', f'/api/reviews/{asin}')
    if not isinstance(entries, list):
        raise SystemExit(f"GET /api/reviews/{asin} did not return a list of decisions, so whether anyone is deciding this run "
                         'row by row can\'t be checked. Nothing recorded.')
    saved = saved_review_entries(os.path.join(run, 'reviews.json'))
    item = next((i for i in plan.get('human_review') or [] if isinstance(i, dict) and i.get('kind') == 'bid'), None)
    if item is not None:
        decided = [e for e in entries + saved if isinstance(e, dict) and e.get('item_id') == item.get('id')
                   and e.get('decision') in DECISIONS]
        if decided:
            raise SystemExit(f"{REVIEW_DECIDED} ({len(decided)} decisions on its bids item {item.get('id')}: python "
                             f'scripts/dashboard.py approvals --asin {asin} --run {run}). Nothing recorded.')
    auto = dict((shared or {}).get('auto') or {})
    auto.update((product or {}).get('auto') or {})
    locks, problem = plan_lanes.lock_table(product, auto.get('lock_weeks'), entries, day.isoformat())
    if problem:
        raise SystemExit(f'{problem}; fix its decisions in data/asins/{asin}.json first (a list of {{id, what, by, until}}). '
                         'Nothing recorded.')
    by_id = {c.get('row_id'): c for c in plan.get('changes') or []}
    declined = [rid for rid in row_ids if rid in by_id and lanes.blocking_lock(by_id[rid], locks, day.isoformat())]
    if declined:
        raise SystemExit(f"these rows of payloads/review/ were declined on the dashboard after the plan: {', '.join(declined)}. "
                         'Save the decisions and plan the run again (python scripts/dashboard.py reviews ... --save '
                         f'{os.path.join(run, "reviews.json")}, then plan.py), and apply what it writes. Nothing recorded.')


def held_approved_message(pending, asin, run):
    """Why approvals won't clear payloads/approved/ (C2), and the two ways on."""
    rows = [p for p in pending if not p.endswith(' (no rows.json)')]
    files = [p for p in pending if p.endswith(' (no rows.json)')]
    if files:
        return ('payloads/approved/ holds payload files without rows.json, so whether they went out, and which rows they '
                f"hold, can't be told ({', '.join(files)}). If they did not go out, re-run with --discard-unapplied. "
                'Nothing written.')
    return (f'payloads/approved/ still holds {len(rows)} rows not recorded as applied. If they went out, run `python '
            f'scripts/dashboard.py applied --asin {asin} --run {run} --folder approved` first. If they did not, re-run with '
            f"--discard-unapplied. The rows: {', '.join(rows)}. Nothing written.")


def decision_day(entry, now):
    """The Singapore date a dashboard decision was made: its `at`, or `now` when it carries no readable time."""
    return ((_moment(entry.get('at')) if isinstance(entry, dict) else None) or now) + SGT


def prune_locks(entries, today):
    """`entries` without the locks that ended more than PRUNE_DAYS days before `today` (a date): (kept, how many dropped).
    A lock whose end can't be read is kept."""
    cutoff = today - dt.timedelta(days=PRUNE_DAYS)
    kept = []
    for d in entries:
        end = lanes.lock_date(d.get('until')) if isinstance(d, dict) and isinstance(d.get('until'), str) else None
        if end is None or end >= cutoff:
            kept.append(d)
    return kept, len(entries) - len(kept)


def write_product(path, product):
    """Write a product file back with the indent it was written with, so only what changed changes."""
    indent = json_indent(path)  # read before the file is opened for writing
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(product, f, indent=indent, ensure_ascii=False)
        f.write('\n')


def lock_weeks(product, shared):
    """How many weeks a decision locks its row: the product's auto.lock_weeks, else config.json's (as plan_lanes merges them)."""
    value = None
    for block in (shared.get('auto'), product.get('auto')):
        if isinstance(block, dict) and block.get('lock_weeks') is not None:
            value = block['lock_weeks']
    weeks = _number(value)
    if weeks is None or weeks <= 0:
        raise SystemExit('auto.lock_weeks (config.json, or the product file) must be a positive number of weeks; '
                         f'it is {value!r}. Nothing written.')
    return weeks


def lock_entries(result, weeks, now):
    """One decline lock {id, what, by, on, until, direction} per declined row, in the dashboard's row order.

    Approvals write no lock here: an approve lock is written by `applied`, once the row has gone out (B4), so an approval
    that never went out never hides its row. `on` is the decision's date in Singapore (today's, when the entry carries no
    readable time), `until` that date plus `weeks` weeks, and `direction` the declined row's move (lanes.direction: 'up',
    'down', 'pause' or 'other'), which tells the planner which proposals the decline holds. A row missing from the plan
    gets no direction, and so holds every move.

    G2 (N2), across weeks: when the plan holds the row by an earlier decline (its change's locked_until, decision
    'decline') from a higher-ranked signer than this decline's, the lock still names that earlier decliner (by, and on
    the day they declined), so a lower "no" this week never lowers who may approve the row again. It holds from this
    decline (`until`), so the higher bar lasts as long as the lock: the safe side of "while its lock holds"."""
    out = []
    for rid in result['order']:
        e = result['decided'].get(rid)
        if e is None or e['decision'] != 'decline':
            continue
        day = decision_day(e, now).date()
        by, on = e['by'].strip(), day.isoformat()
        change = result['rows'].get(rid)
        earlier = (change or {}).get('decided_by')
        if ((change or {}).get('locked_until') and change.get('decision') == 'decline' and isinstance(earlier, str)
                and LEVELS.index(signer_level(earlier)) > LEVELS.index(signer_level(by))):
            by, on = earlier.strip(), change['decided_on'] if _iso_day(change.get('decided_on')) else on
        lock = dict(id=rid, what='decline', by=by, on=on, until=(day + dt.timedelta(weeks=weeks)).isoformat())
        if change is not None:
            lock['direction'] = lanes.direction(change)
            if change.get('owner_kind'):
                lock['owner_kind'] = change['owner_kind']  # a business row's search is locked per shopper kind (lock_table)
        out.append(lock)
    return out


def json_indent(path, default=1):
    """The indent a product file is written with (its first indented line), so a rewrite changes only what it must."""
    with open(path, encoding='utf-8') as f:
        for line in f:
            body = line.lstrip(' ')
            if body.startswith('"') and body != line:
                return len(line) - len(body)
    return default


def closed_text(item):
    """How a closed bids item was closed, for approvals' message: 'superseded by <what>' when its resolution says
    "Superseded by ...", else '<status> (<resolution>)'."""
    note = str(item.get('resolution') or '').strip()
    if note.lower().startswith('superseded by '):
        return 'superseded by ' + note[len('superseded by '):]
    return f"{item.get('status')}" + (f' ({note})' if note else '')


def write_window(now, apply_after):
    """Compatibility interface: execute authorized audits any day, including legacy Monday-dated plans.

    apply_after encoded the retired weekday policy, not a person's execution schedule.
    """
    return lanes.us_write_window_open(now, apply_after), None


def cmd_approvals(a):
    """Approved rows to <run>/payloads/approved/, declines to the product file's locks. Never writes to Amazon.

    An item that is active or resolved (a person closed it; no newer run did) runs normally. A dismissed one (superseded
    by a newer run, or dismissed by a person) runs in decisions-only mode: its declines become locks, its approvals are not
    applied (they are approved again on the newest run), and no decline lock is released.

    It refuses, writing nothing, a run applied whole through review/ (C4), and an approved/ folder holding rows `applied`
    hasn't recorded, unless --discard-unapplied says they did not go out (C2). Calendar dates do not defer approvals.
    Apply emitted payloads through MAP, verify independently, and only then record them with applied.
    --dry-run (which hands nothing out) and decisions-only mode (nothing of a closed item goes out) are not refused."""
    now = dt.datetime.now(dt.timezone.utc) if not a.now else _moment(a.now)
    if now is None:
        raise SystemExit(f"--now must be an ISO time in UTC, such as 2026-10-19T15:00:00Z; got {a.now!r}")
    cfg = config()
    path = product_path(a.asin, a.data)
    product = load_json(path)
    if not product:
        raise SystemExit('Missing product file: ' + a.asin)
    plan = load_json(os.path.join(a.run, 'plan.json'))
    if not plan:
        raise SystemExit(f'No plan.json in {a.run}')
    summary = (plan.get('summary') or [{}])[0]
    if summary.get('asin') != a.asin:
        raise SystemExit(f'{a.run} holds the plan for {summary.get("asin")}, not {a.asin}')
    item = bids_item(plan)
    held = next((i for i in product.get('human_review') or [] if isinstance(i, dict) and i.get('id') == item['id']), None)
    if held is None:
        raise SystemExit(f"The product file for {a.asin} doesn't hold this run's bids item {item['id']}: publish the run "
                         '(or git pull) first.')
    status = held.get('status')
    decisions_only = status not in ACTIVE_STATUSES + ('resolved',)
    message = (f"This run's bids item was {closed_text(held)}: declines were recorded as locks, approvals were not applied "
               '(approve the rows on the newest run)') if decisions_only else None
    _, unreadable = plan_lanes.lock_table(product)
    if unreadable:
        raise SystemExit(f'{unreadable}; fix its decisions in data/asins/{a.asin}.json first (a list of {{id, what, by, until}}). '
                         'Nothing written.')
    weeks = lock_weeks(product, cfg)
    live = read_live(a.live) if a.live else None
    payloads = os.path.join(a.run, 'payloads')
    out_dir = os.path.join(payloads, 'approved')
    went_out = read_applied_record(os.path.join(payloads, APPLIED_ROWS))
    applied = {rid: e['date'] for rid, e in went_out.items()}
    whole = sorted(e['date'] for e in went_out.values() if e['folder'] == 'review')
    if whole:
        # C4: review/ went out whole (the preview's yes), so the run's row-by-row decisions send nothing more
        raise SystemExit(f'this run was applied whole on {whole[0]} (payloads/review/ went out and `applied` recorded it): '
                         'nothing of its bids item goes out from approvals now (its declines reach the next plan through '
                         'its saved reviews.json). Nothing written.')
    # C2: what approved/ handed out for an apply is reconciled (recorded by `applied`) before anything replaces it
    pending = unreconciled_approved(out_dir, applied)
    if pending and not getattr(a, 'discard_unapplied', False):
        raise SystemExit(held_approved_message(pending, a.asin, a.run))
    apply_after = summary.get('apply_after')
    window_open, shut_why = write_window(now, apply_after)
    entries = call('GET', f'/api/reviews/{a.asin}')  # the only call: a read of the dashboard
    if not isinstance(entries, list):
        raise SystemExit(f'GET /api/reviews/{a.asin} did not return a list of decisions')
    result = evaluate(plan, entries, live, cfg, a.asin, applied, product=product, today=(now + SGT).date())
    if decisions_only:
        # nothing of a closed item goes out: every approval on it is listed as not applied, and none releases a decline
        not_applied = [dict(row_id=rid, reason=f"not applied: this run's bids item was {closed_text(held)}")
                       for rid in result['order'] if (result['decided'].get(rid) or {}).get('decision') == 'approve']
        result = dict(result, files={}, row_ids={}, approved_rows=[], no_payload=[], capped=[], unlocked=[], skipped=not_applied,
                      agreed_held=[])
    locks = lock_entries(result, weeks, now)
    existing = product.get('decisions') or []
    # A row approved but held back releases the lock an earlier *decline* left on it (the team reversed that decline). An
    # approve lock is never released here: `applied` wrote it when the row went out, and it must stand while a later run
    # holds the row back. A row approved and emitted keeps its decline lock until `applied` replaces it with an approve one.
    held_back = set(result['unlocked'])
    released = [d for d in existing if str(d['id']) in held_back and d.get('what') == 'decline']
    kept = [d for d in existing if str(d['id']) not in {str(lock['id']) for lock in locks} and not any(d is r for r in released)]
    pruned = 0
    if kept + locks != existing:
        decisions, pruned = prune_locks(kept + locks, (now + SGT).date())
    # who approved each row that goes out, for the approve lock `applied` writes once it has; and (G1) each approved row a
    # person carries out by hand (no payload: a stop-loss review), which log_invest reads as that person's decision
    record = {}
    for rid in dict.fromkeys([r for ids in result['row_ids'].values() for r in ids]
                             + [p['row_id'] for p in result['no_payload']]):
        e = result['decided'].get(rid)
        if e is not None:
            record[rid] = dict(by=e['by'].strip(), on=decision_day(e, now).date().isoformat(), at=e.get('at'))

    if not a.dry_run:
        for old in glob.glob(os.path.join(glob.escape(out_dir), '*.json')):
            if os.path.basename(old) != OLD_APPLIED:  # N9: Task 7's record stays
                os.remove(old)  # an earlier approvals run's files must not outlive its decisions (reconciled above)
        if os.path.exists(os.path.join(payloads, APPROVED_RECORD)):
            os.remove(os.path.join(payloads, APPROVED_RECORD))
        if result['files']:
            os.makedirs(out_dir, exist_ok=True)
            for name, rows in result['files'].items():
                write_payload_json(os.path.join(out_dir, name), rows, separators=(',', ':'))
            write_payload_json(os.path.join(out_dir, ROWS_FILE), result['row_ids'], indent=1)
        if record:
            os.makedirs(payloads, exist_ok=True)
            write_payload_json(os.path.join(payloads, APPROVED_RECORD), record, indent=1, ensure_ascii=False)
        if kept + locks != existing:
            product['decisions'] = decisions
            write_product(path, product)

    files = {name: len(rows) for name, rows in result['files'].items()}
    approved = sum(files.values())
    warnings = []
    if live is None:
        warnings.append('No --live file: the approved rows were not checked against the live account. Save MAP list_resources '
                        'for the plan\'s keywords and targets and pass it as --live before applying.')
    elif result['not_checked']:
        kinds = ', '.join(f'{kind} x{n}' for kind, n in sorted(result['not_checked'].items()))
        warnings.append(f"Approved rows with no live keyword or target id were not checked against the account ({kinds}).")
    for line in warnings:
        print('WARNING: ' + line, file=sys.stderr)
    if message:
        print('NOTE: ' + message, file=sys.stderr)
    print(json.dumps(dict(
        asin=a.asin, run=os.path.basename(os.path.normpath(a.run)), item=item['id'], dry_run=bool(a.dry_run),
        item_status=status, mode='decisions_only' if decisions_only else 'normal', message=message,
        approved=approved, approved_rows=len(result['approved_rows']), discarded=pending,
        declined=sum(1 for e in result['decided'].values() if e['decision'] == 'decline'),
        skipped=result['skipped'], ignored=result['ignored'], files=files, no_payload=result['no_payload'],
        capped=result['capped'], agreed_held=result['agreed_held'], checked_live=live is not None,
        not_drift_checked=result['not_checked'] if live is not None else None,
        locks_written=0 if a.dry_run else len(locks),
        locks_released=0 if a.dry_run else len(released),  # decline locks only (see above)
        locks_pruned=0 if a.dry_run else pruned,
        apply_after=apply_after, write_window_open=window_open, warnings=warnings),
        ensure_ascii=False, indent=1))


def utc_now():
    """Now, in UTC: the one clock `reviews` stamps its saves with (tests set it)."""
    return dt.datetime.now(dt.timezone.utc)


def cmd_reviews(a):
    """Save the dashboard's decisions on the product (GET /api/reviews/<ASIN>, as it comes) to --save, normally the run
    folder about to be planned: plan.py turns every decline in it into a lock (B2). The file is {asin, saved_at (ISO UTC),
    entries}, so plan.py can refuse one for another product or one saved more than a day before the run (C6). It only
    reads the dashboard.

    It also saves Growth's clicks on the For Growth item (GET /api/items/<ASIN>, "Picked up" and "Copy pushed") beside
    it, as item_statuses.json in the same shape, for publish to move onto the item (apply_statuses); reviews.json is
    unchanged, so plan.py's checks of it hold. A dashboard that can't answer that (no status route yet) leaves the
    decisions saved, with a warning."""
    entries = call('GET', f'/api/reviews/{a.asin}')
    if not isinstance(entries, list):
        raise SystemExit(f'GET /api/reviews/{a.asin} did not return a list of decisions. Nothing saved.')
    saved_at = utc_now().astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    folder = os.path.dirname(os.path.abspath(a.save))
    os.makedirs(folder, exist_ok=True)
    part = a.save + '.part'
    write_payload_json(part, dict(asin=a.asin, saved_at=saved_at, entries=entries), indent=1, ensure_ascii=False)
    os.replace(part, a.save)  # a half-written file must never be read as the team's decisions
    items = {}
    for e in entries:
        if isinstance(e, dict):
            items[str(e.get('item_id'))] = items.get(str(e.get('item_id')), 0) + 1
    try:
        statuses, why = call('GET', f'/api/items/{a.asin}'), None
    except SystemExit as e:  # call() turns an HTTP error into SystemExit: the decisions above stay saved
        statuses, why = None, str(e.code)
    statuses_path = os.path.join(folder, ITEM_STATUSES)
    if isinstance(statuses, list):
        part = statuses_path + '.part'
        write_payload_json(part, dict(asin=a.asin, saved_at=saved_at, entries=statuses), indent=1, ensure_ascii=False)
        os.replace(part, statuses_path)
    else:
        print(f'WARNING: item statuses not saved ({why or f"GET /api/items/{a.asin} did not return a list"}): the For '
              'Growth item keeps the status its product file holds.', file=sys.stderr)
    print(json.dumps(dict(asin=a.asin, saved=a.save, saved_at=saved_at, decisions=len(entries),
                          declines=sum(1 for e in entries if isinstance(e, dict) and e.get('decision') == 'decline'),
                          items=items, item_statuses=len(statuses) if isinstance(statuses, list) else None,
                          item_statuses_saved=statuses_path if isinstance(statuses, list) else None),
                     ensure_ascii=False, indent=1))


def rows_named(values, row_ids, folder):
    """E5: the rows `applied --rows` names, in the folder's rows.json order. Each value is a row id, or several separated by
    commas (a value that is itself a row id of the folder is taken whole, so an id holding a comma can be given on its own).
    A name the folder's rows.json doesn't hold, or none at all, stops the command: only rows handed out for the apply can
    have gone out."""
    known = set(row_ids)
    named = []
    for value in values:
        text = str(value).strip()
        named += [text] if text in known else [p.strip() for p in text.split(',') if p.strip()]
    unknown = [n for n in dict.fromkeys(named) if n not in known]
    if unknown:
        raise SystemExit(f"--rows names rows payloads/{folder}/rows.json doesn't hold: {', '.join(unknown)}. Name the rows of "
                         'the folder that went out (read back), as its rows.json writes them. Nothing recorded.')
    if not named:
        raise SystemExit('--rows names no rows: name the rows of the folder that went out (read back). Nothing recorded.')
    return [rid for rid in row_ids if rid in set(named)]


def cmd_applied(a):
    """Record that a payload folder of a run went out: its rows (from the folder's rows.json) are added to
    <run>/payloads/applied_rows.json with the day and the folder (C4), and each row applied from approved/ gets an approve
    lock in the product file's decisions. Rows from auto/ and review/ get no lock (an automatic row needs none, and a
    whole-run yes on the preview is not a decision on a row), except a creation, which from any folder gets a create lock
    (kind 'create', C3) so its search is never created again. An empty folder records nothing and says so (C7).

    Before any folder is recorded (and, as its --dry-run, before it is applied) it refuses a creation whose search a create
    lock already records, for approved/ as for auto/ and review/ (C3, R2); the rows this run already recorded are exempt.
    For review/ it also reads the dashboard and refuses while the run is being decided row by row, or a row of review/ was
    declined after the plan (C4). --record-anyway skips those checks for a folder that already went out. Otherwise it reads
    the dashboard only to name an approver approvals did not record, and it never writes to Amazon. It can't tell whether
    a folder went out: run it for real only after the MAP apply went through.

    The check before every apply retains non-calendar safeguards for every folder. Weekends and legacy apply_after
    dates never defer execution (Kim, 2026-10-24). E5 (I5): --rows names the rows of the
    folder that went out (read back) when only part of it did: only those are recorded and locked; the rest stays
    unrecorded, so approvals still refuses until it is recorded or, for approved/, discarded.

    G4 (m1): its --dry-run refuses a folder any of whose rows were recorded from it: "this folder partly went out on
    <date>; don't apply it again" (or "went out", when every row is recorded). G3 (N3): recording any row of a Sponsored
    Brands video build (one 7_sb_new_campaigns.json spec) create-locks the build's other keyword rows in the folder too
    (kind 'create', by_hand), and the output's add_by_hand lists them: add them by hand to the campaign that now exists.
    The check also refuses any row of a campaign whose build already went out (built_sb_campaigns).

    Autonomous runs (2026-10-22, decision 98): --folder auto, its check and its record, refuses a product whose Auto lane is
    off (plan_lanes.auto_enabled: a guard switched it off, autonomy.py); --record-anyway records what already went out."""
    if a.folder not in APPLY_FOLDERS:
        raise SystemExit(f"--folder must be one of {', '.join(APPLY_FOLDERS)}; {a.folder!r} is never applied "
                         '(payloads/held/ holds what a decision or the planner keeps back).')
    day = _iso_day(a.date) if a.date else dt.date.fromisoformat(sgt_today())
    if day is None:
        raise SystemExit(f'--date must be YYYY-MM-DD, the day the folder went out (Singapore time); got {a.date!r}')
    now = dt.datetime.now(dt.timezone.utc) if not getattr(a, 'now', None) else _moment(a.now)
    if now is None:
        raise SystemExit(f"--now must be an ISO time in UTC, such as 2026-10-19T15:00:00Z; got {a.now!r}")
    cfg = config()
    path = product_path(a.asin, a.data)
    product = load_json(path)
    if not product:
        raise SystemExit('Missing product file: ' + a.asin)
    plan = load_json(os.path.join(a.run, 'plan.json'))
    if not plan:
        raise SystemExit(f'No plan.json in {a.run}')
    summary = (plan.get('summary') or [{}])[0]
    if summary.get('asin') != a.asin:
        raise SystemExit(f'{a.run} holds the plan for {summary.get("asin")}, not {a.asin}')
    payloads = os.path.join(a.run, 'payloads')
    folder = os.path.join(payloads, a.folder)
    rows_path = os.path.join(folder, ROWS_FILE)
    payload_files_there = [p for p in glob.glob(os.path.join(glob.escape(folder), '*.json'))
                           if os.path.basename(p) not in (ROWS_FILE, OLD_APPLIED)]
    if not os.path.exists(rows_path) and payload_files_there:
        raise SystemExit(f"{folder} has payload files but no {ROWS_FILE}, so which rows went out can't be told. "
                         'Plan the run again (or run approvals again) and apply what it writes. Nothing recorded.')
    row_ids = list(dict.fromkeys(rid for ids in read_rows_file(rows_path).values() for rid in ids)) if os.path.exists(
        rows_path) else []
    in_folder = row_ids
    if row_ids and getattr(a, 'rows', None):
        row_ids = rows_named(a.rows, row_ids, a.folder)  # E5: only the rows that went out
    if not row_ids:
        # C7: a week where nothing went out is a normal week: say so, write nothing (no applied_rows.json), and don't fail
        print(json.dumps(dict(asin=a.asin, run=os.path.basename(os.path.normpath(a.run)), folder=a.folder,
                              date=day.isoformat(), dry_run=bool(a.dry_run), rows=0, recorded=0, already=0, locks_written=0,
                              locks_pruned=0, read_dashboard=False, warnings=[],
                              note=f'Nothing to record: payloads/{a.folder}/ holds no payloads in {a.run}. Nothing written.'),
                         ensure_ascii=False, indent=1))
        return
    # autonomous runs (2026-10-22, decision 98): auto/ goes out only while the product's Auto lane is on (config.json, with
    # the product file's own auto block over it); a guard that switched it off (autonomy.py) stops the folder. What already
    # went out is still recorded, with --record-anyway
    if a.folder == 'auto' and not plan_lanes.auto_enabled(cfg, product) and not getattr(a, 'record_anyway', False):
        raise SystemExit(f"{a.asin}'s Auto lane is off (its product file's auto.enabled, or config.json's), so payloads/auto/ "
                         "is not applied: its rows wait for the next plan, as proposals. If rows of it already went out, "
                         'record them with --rows ... --record-anyway. Nothing recorded.')
    applied_path = os.path.join(payloads, APPLIED_ROWS)
    raw = read_applied_raw(applied_path)
    by_id = {c.get('row_id'): c for c in plan.get('changes') or []}
    if a.dry_run and any((by_id.get(rid) or {}).get(listing_size.MARKER) for rid in row_ids):
        size_problem = listing_size.preapply_problem(
            [by_id[rid] for rid in row_ids if rid in by_id], a.run, product, own_sizes(a.asin, product),
            product_sizes(a.asin, product), dimension_pairs, now.astimezone(listing_size.SGT).date().isoformat(), now)
        if size_problem:
            raise SystemExit('Live listing size verification refuses these pauses: ' + size_problem
                             + ' Refresh the listing evidence and re-plan; nothing applied or recorded.')
    scope_problems = {rid: why for rid in row_ids
                      if (why := ownership_scope.reason(by_id.get(rid), product, plan.get('changes') or [])
                          or (by_id.get(rid) or {}).get('ownership_scope_blocked'))}
    if 'ownership_scope' in product:
        folder_changes = [by_id[rid] for rid in in_folder if rid in by_id]
        for payload_path in payload_files_there:
            problem = ownership_scope.payload_reason(load_json(payload_path), product, folder_changes)
            if problem:
                scope_problems['payload: ' + os.path.basename(payload_path)] = problem
    if scope_problems and (a.dry_run or not getattr(a, 'record_anyway', False)):
        raise SystemExit('Ownership scope refuses these rows: ' + '; '.join(f'{rid}: {why}' for rid, why in scope_problems.items())
                         + '. Re-plan within the exclusive scope; no writes or records permitted.')
    if a.dry_run:
        # G4 (m1): a folder any row of which `applied` recorded from it went out, whole or in part: it is never applied
        # again (its files still hold every row, the recorded ones included). An older record that doesn't name its
        # folder counts too (the safe side)
        gone = {rid: _applied_entry(raw[rid]) for rid in in_folder if rid in raw}
        gone = {rid: e for rid, e in gone.items() if e['folder'] in (a.folder, None)}
        if gone:
            first = min(e['date'] for e in gone.values())
            if len(gone) < len(in_folder):
                raise SystemExit(f"payloads/{a.folder}/: this folder partly went out on {first}; don't apply it again — "
                                 're-plan in a new run folder or settle with approvals '
                                 f'({len(gone)} of its {len(in_folder)} rows recorded in payloads/{APPLIED_ROWS}). '
                                 'Nothing recorded.')
            raise SystemExit(f'payloads/{a.folder}/: this folder went out on {first} (every row is recorded in '
                             f"payloads/{APPLIED_ROWS}); don't apply it again. Nothing recorded.")
    warnings = []
    if getattr(a, 'record_anyway', False):
        if scope_problems:
            warnings.append('--record-anyway records historical truth only; ownership scope violations: '
                            + '; '.join(f'{rid}: {why}' for rid, why in scope_problems.items()))
        skipped_checks = 'a creation already made elsewhere'
        if a.folder == 'review':
            skipped_checks += ', whether anyone decided this run row by row, or declined a row of review/ after the plan'
        warnings.append(f'--record-anyway: the checks were skipped ({skipped_checks}); payloads/{a.folder}/ is recorded as '
                        'gone out' + (', so approvals sends nothing more for this run.' if a.folder == 'review' else '.'))
    else:
        # C3, R2: a folder written earlier (at plan time, or by approvals before another folder went out) must not create a
        # search a later `applied` recorded as created (last week settled after this run was planned, or another run's
        # review/ made it while this approved/ waited). The rows this run already recorded are exempt. The check to run
        # before the apply is this command's --dry-run, for every folder.
        created = created_searches(product, {}, by_id, day)
        built = built_sb_campaigns(product, {}, by_id, day)  # G3: a Sponsored Brands video build is created once
        again = []
        for rid in row_ids:
            c = by_id.get(rid) or {}
            key = plan_lanes.creation_key(c.get('type'), c.get('keyword'), c.get('owner_kind'))
            if rid not in raw and key in created:
                again.append(f'{rid} (on {created[key]})')
            elif rid not in raw and _sb_campaign(c) in built:
                again.append(f'{rid} (its campaign {_sb_campaign(c)} was created on {built[_sb_campaign(c)]})')
        if again:
            if a.folder == 'approved':
                what_next = ('Run approvals again with --discard-unapplied (this folder did not go out) and apply what it '
                             'writes, which holds a creation already made.')
            else:
                what_next = 'Save the decisions and plan the run again, and apply what it writes.'
            raise SystemExit(f"these rows of payloads/{a.folder}/ create a search already created: {', '.join(again)}. "
                             f'{what_next} If the folder already went out through MAP, record it with --record-anyway. '
                             'Nothing recorded.')
        if a.folder == 'review':
            check_review_route(a.asin, a.run, plan, product, cfg, row_ids, day)
    new = [rid for rid in row_ids if rid not in raw]
    for rid in new:
        raw[rid] = dict(date=day.isoformat(), folder=a.folder)  # a row that already went out keeps its first day and folder
    applied = {rid: _applied_entry(v)['date'] for rid, v in raw.items()}

    locks, pruned, asked = [], 0, False
    # approved/: every row locks (B4). Any folder: a creation locks with kind 'create' (C3), so the search is never
    # created again, whatever row id a later run gives it
    creations = {rid for rid in row_ids if (by_id.get(rid) or {}).get('type') in plan_lanes.CREATION_FAMILY}
    lock_ids = row_ids if a.folder == 'approved' else [rid for rid in row_ids if rid in creations]
    # G3 (N3): a Sponsored Brands video build is created once. When any row of a build (one campaign, its ad group and
    # video ad, and up to 8 keywords: one spec of 7_sb_new_campaigns.json) is recorded, its campaign exists: the build's
    # other keyword rows in the folder get create locks too (by_hand), so nothing hands the build out again, and they are
    # listed to be added to that campaign by hand
    builds = sb_builds(row_ids, in_folder, by_id)
    by_hand = [rid for rows in builds.values() for rid in rows if rid not in raw]
    creations.update(by_hand)
    lock_ids = list(lock_ids) + by_hand
    if lock_ids:
        _, unreadable = plan_lanes.lock_table(product)
        if unreadable:
            raise SystemExit(f'{unreadable}; fix its decisions in data/asins/{a.asin}.json first (a list of {{id, what, by, '
                             'until}}). Nothing recorded.')
        weeks = lock_weeks(product, cfg)
        record = (load_json(os.path.join(payloads, APPROVED_RECORD), {}) or {}) if a.folder == 'approved' else {}
        record = record if isinstance(record, dict) else {}
        if a.folder == 'approved' and any(not isinstance(record.get(rid), dict) for rid in row_ids):
            # approvals did not record who approved some of these rows: ask the dashboard once (a read)
            asked = True
            entries = call('GET', f'/api/reviews/{a.asin}')
            decided = {}
            if isinstance(entries, list):
                item = next((i for i in plan.get('human_review') or [] if isinstance(i, dict) and i.get('kind') == 'bid'), None)
                if item is not None:
                    decided, _, _ = latest_decisions(item, entries)
            now = dt.datetime.combine(day, dt.time(), dt.timezone.utc)
            for rid, e in decided.items():
                if e['decision'] == 'approve' and not isinstance(record.get(rid), dict):
                    record[rid] = dict(by=e['by'].strip(), on=decision_day(e, now).date().isoformat(), at=e.get('at'))
        for rid in lock_ids:
            info = record.get(rid) if isinstance(record.get(rid), dict) else {}
            went = dt.date.fromisoformat(applied.get(rid, day.isoformat()))  # a by_hand row: the day its build went out
            lock = dict(id=rid, what='approve', by=info.get('by') if isinstance(info.get('by'), str) and info['by'].strip() else None,
                        on=info.get('on') if _iso_day(info.get('on')) else went.isoformat(),
                        until=(went + dt.timedelta(weeks=weeks)).isoformat())
            change = by_id.get(rid)
            if change is not None:
                lock['direction'] = lanes.direction(as_written(change))
                lock['owner_kind'] = change.get('owner_kind')  # per shopper kind (plan_lanes.lock_table); None is dropped below
            if rid in creations:
                lock.update(kind='create', search=norm(change.get('keyword') or '') or None, created_on=went.isoformat(),
                            campaign=_sb_campaign(change), by_hand=True if rid in by_hand else None)
            locks.append({k: v for k, v in lock.items() if v is not None})
        mine = {lock['id'] for lock in locks}
        # an approve lock replaces whatever lock the row had (a decline the team has now reversed, an older approval)
        decisions, pruned = prune_locks([d for d in product.get('decisions') or [] if str(d.get('id')) not in mine] + locks, day)

    if not a.dry_run:
        write_payload_json(applied_path, raw, indent=1, ensure_ascii=False)
        if locks:
            product['decisions'] = decisions
            write_product(path, product)
    partial = len(row_ids) < len(in_folder)
    left = [rid for rid in in_folder if rid not in raw]
    if partial and left:
        # G4 (m1): a folder that partly went out is never applied again (its check refuses it)
        if a.folder == 'approved':
            what_next = ('Never apply this folder again. If they did not go out, run approvals with --discard-unapplied: it '
                         'hands out only the rows not recorded. If some did go out (read back), record those with --rows first')
        else:
            what_next = (f"Don't apply payloads/{a.folder}/ again: the rest waits for next week's plan. If some did go out "
                         '(read back), record those with --rows')
        warnings.append(f"{len(left)} rows of payloads/{a.folder}/ are not recorded: {', '.join(left)}. {what_next}.")
    add_by_hand = [dict(campaign=name, keywords=[by_id[rid].get('keyword') for rid in rows if rid in by_hand],
                        row_ids=[rid for rid in rows if rid in by_hand]) for name, rows in builds.items()
                   if any(rid in by_hand for rid in rows)]
    for build in add_by_hand:
        warnings.append(f"add these keywords by hand to the campaign that now exists ({build['campaign']}): "
                        f"{', '.join(build['keywords'])}. The rest of its build went out, so they are create-locked: nothing "
                        'hands the build out again.')
    print(json.dumps(dict(asin=a.asin, run=os.path.basename(os.path.normpath(a.run)), folder=a.folder, date=day.isoformat(),
                          dry_run=bool(a.dry_run), rows=len(row_ids), recorded=len(new), already=len(row_ids) - len(new),
                          partial=partial, left_unrecorded=left if partial else [], add_by_hand=add_by_hand,
                          locks_written=0 if a.dry_run else len(locks), locks_pruned=0 if a.dry_run else pruned,
                          read_dashboard=asked or (a.folder == 'review' and not getattr(a, 'record_anyway', False)),
                          warnings=warnings), ensure_ascii=False, indent=1))
    for line in warnings:
        print('WARNING: ' + line, file=sys.stderr)


def cmd_lineup(a):
    doc, product = build_lineup_doc(a.asin, a.date or dt.date.today().isoformat(), a.by, a.data)
    body = json.dumps(doc, ensure_ascii=False, separators=(',', ':'))
    size = dict(bytes=len(body.encode('utf-8')))
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(body)
    if a.dry_run:
        print(json.dumps(dict(dry_run=True, out=a.out, **size), indent=1))
        return
    res = put_page(a, doc, product)
    url = config()['dashboard']['url'].rstrip('/')
    print(json.dumps(dict(res, page=f'{url}/#/{a.asin}', **size), indent=1))


def cmd_refresh(a):
    """Republish a page from the product file: a lined-up product is rebuilt whole (as lineup does); an AI-managed one
    keeps its latest run's tables from the live page. With --run, the product file first records that run's SQP totals
    and data stage (record_run_history) and its For Growth gate counts (store_growth_run), so the file written after the
    publish carries them; --dry-run records nothing. A run folder whose plan is for another product is refused."""
    cfg = config()
    run = getattr(a, 'run', None)    # cmd_rank hands over its own arguments, which have no --run
    if run and not os.path.isdir(run):
        raise SystemExit(f'no run folder at {run}')
    product = load_json(product_path(a.asin, a.data))
    if product is None:
        raise SystemExit(f'missing product file data/asins/{a.asin}.json')
    recorded = {}
    if (product.get('registry') or {}).get('stage') == 'queued':
        if run:
            raise SystemExit(f'{a.asin} is lined up (registry stage queued) and not AI-managed yet, so it has no run to record: '
                             'refresh it without --run')
        doc, product = build_lineup_doc(a.asin, dt.date.today().isoformat(), a.by, a.data)
        doc['publish_kind'] = 'Page refresh'
        if a.note:
            doc['activity_note'] = a.note
    else:
        if run:
            held = ((load_json(os.path.join(run, 'plan.json')) or {}).get('summary') or [{}])[0].get('asin')
            if held and held != a.asin:    # another product's totals and stage would stick in this one's file
                raise SystemExit(f'{run} holds the plan for {held}, not {a.asin}')
            recorded = record_run_history(product, run)
            # the run's For Growth gate counts (and its anchor, when the file has none): R6, as publish keeps them
            recorded['growth_stored'] = store_growth_run(product, run)
        doc = refresh_doc(call('GET', f'/api/products/{a.asin}'), product, cfg, a.note)
        doc['published_by'] = a.by
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(json.dumps(doc, ensure_ascii=False, separators=(',', ':')))
    if a.dry_run:
        print(json.dumps(dict(dry_run=True, out=a.out, asin=a.asin, name=doc.get('name'), bytes=len(json.dumps(doc).encode('utf-8')),
                              **recorded), indent=1))
        return
    res = put_page(a, doc, product)
    print(json.dumps(dict(res, page=f"{cfg['dashboard']['url'].rstrip('/')}/#/{a.asin}", **recorded), indent=1))


def cmd_rank(a):
    """Store the product's daily organic rank (from saved Rank Radar pages) in its product file, then refresh the page."""
    paths = sorted(p for pat in a.radar for p in glob.glob(pat))
    if not paths:
        raise SystemExit('no radar pages matched ' + ' '.join(a.radar))
    path = product_path(a.asin, a.data)
    product = load_json(path)
    if product is None:
        raise SystemExit(f'missing product file data/asins/{a.asin}.json')
    block = rank_block(product, read_pages(paths), a.days, a.top, dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    if a.dry_run:
        print(json.dumps(dict(dry_run=True, asin=a.asin, start=block['start'], end=block['end'], dates_with_data=block['dates_with_data'],
                              summary=block['summary'], searches=[(x['kw'], x['now'], x['week']) for x in block['keywords']]), indent=1))
        return
    product['rank'] = block
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(product, f, indent=1, ensure_ascii=False)
        f.write('\n')
    s = block['summary']
    a.note = a.note or (f"Organic rank updated to {day_text(block['end'])}: {s['top10']} of {s['searches']} main searches in the top 10; "
                        f"7 days: {s['up7']} up, {s['down7']} down" if block['end'] else 'Rank Radar has no daily readings yet')
    cmd_refresh(a)


def day_text(d):
    return dt.date.fromisoformat(d).strftime('%b %-d') if os.name != 'nt' else dt.date.fromisoformat(d).strftime('%b %#d')


def cmd_site(a):
    out = {}
    for name in SITE_FILES:
        with open(os.path.join(SITE_DIR, name), 'rb') as f:
            out[name] = call('PUT', f'/api/site/{name}', f.read()).get('bytes')
    print(json.dumps(dict(uploaded=out, url=config()['dashboard']['url']), indent=1))


def cmd_list(a):
    for c in call('GET', '/api/products'):
        mine = ((load_json(product_path(c.get('asin'))) or {}).get('dashboard') or {}).get('version')
        sync = ('in sync' if mine == c.get('version') else 'no local record' if not mine
                else 'the page is newer than your product file: git pull (or ask whoever published to push)')
        print(f"{c.get('asin')}  {c.get('name') or c.get('product')!s:<44} {c.get('version')}  published {str(c.get('published_at'))[:16]} "
              f"by {c.get('published_by')}  | {sync}")


def cmd_claim(a):
    body = dict(what=a.what, until=a.until, by=a.by or default_by(), force=a.force)
    res = call('PUT', f'/api/work/{a.asin}', json.dumps({k: v for k, v in body.items() if v not in (None, False)}))
    c = res.get('claim') or {}
    print(f"{c.get('by')} is working on {a.asin} ({c.get('product') or ''}): {c.get('what')}" + (f" until {c['until']}" if c.get('until') else ''))


def cmd_release(a):
    res = call('DELETE', f'/api/work/{a.asin}', json.dumps({k: v for k, v in dict(note=a.note, by=a.by or default_by()).items() if v}))
    print(f"{a.asin}: " + ('released' if res.get('released') else 'nobody had claimed it' + (' (note logged)' if a.note else '')))


def cmd_note(a):
    res = call('POST', '/api/activity', json.dumps({k: v for k, v in dict(text=a.text, asin=a.asin, by=a.by or default_by()).items() if v}))
    e = res.get('event') or {}
    print(f"logged: {e.get('by')} · {e.get('asin') or 'all products'} · {e.get('text')}")


def cmd_team(a):
    work = call('GET', '/api/work')
    print('Working now:' if work else 'Nobody has claimed a product.')
    for c in work:
        print(f"  {c.get('asin')} {c.get('product') or '':<20} {c.get('by'):<12} {c.get('what')}  since {str(c.get('since'))[:16]}"
              + (f"  until {c['until']}" if c.get('until') else '') + ('  (stale)' if c.get('stale') else ''))
    q = f"?limit={a.limit}" + (f"&asin={a.asin}" if a.asin else '')
    print('\nRecent activity:')
    for e in call('GET', '/api/activity' + q):
        print(f"  {str(e.get('at'))[:16]}  {e.get('by'):<12} {e.get('kind'):<8} {e.get('asin') or '':<11} "
              f"{e.get('label') or ''} {e.get('state') or ''} {e.get('text') or ''}".rstrip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    review = sub.add_parser('review', help='update a Needs human item locally; never publishes or changes prices')
    review.add_argument('--asin', required=True)
    review.add_argument('--id', required=True)
    review.add_argument('--status', required=True, choices=['open', 'in_progress', 'waiting_approval', 'resolved', 'dismissed'])
    review.add_argument('--owner')
    review.add_argument('--note', required=True)
    review.add_argument('--data')
    review.add_argument('--dry-run', action='store_true')
    review.set_defaults(fn=cmd_review)
    approvals = sub.add_parser('approvals', help="turn the team's approvals on a run's Bids item into payloads/approved/, and its "
                                                 'declines into locks; reads the dashboard, never writes to Amazon')
    approvals.add_argument('--asin', required=True)
    approvals.add_argument('--run', required=True, help='the run folder whose plan.json holds the Bids item')
    approvals.add_argument('--live', help='MAP list_resources rows (keywordId/targetId, bid, state) saved to a file: rows that '
                                          'moved since the plan are left out')
    approvals.add_argument('--now', help='ISO time in UTC, for deterministic execution checks (default: now)')
    approvals.add_argument('--data', help='shared data folder (default: config.json data_dir, else <skill>/data)')
    approvals.add_argument('--dry-run', action='store_true', help='work it out and print it, write nothing')
    approvals.add_argument('--discard-unapplied', action='store_true',
                           help='only when payloads/approved/ did NOT go out: clear its rows that applied_rows.json does not '
                                'record (the output names them); without it, approvals refuses to replace them')
    approvals.set_defaults(fn=cmd_approvals)
    reviews = sub.add_parser('reviews', help="save the dashboard's decisions on a product (GET /api/reviews/<ASIN>) for the "
                                             'next plan: python dashboard.py reviews --asin <ASIN> --save <run>/reviews.json')
    reviews.add_argument('--asin', required=True)
    reviews.add_argument('--save', required=True, help='where to save them: the run folder plan.py is about to plan, as '
                                                       "reviews.json (Growth's clicks go beside it as item_statuses.json)")
    reviews.set_defaults(fn=cmd_reviews)
    gr = sub.add_parser('growth', help='For Growth on one product file: --anchor (the anchor and the next listing pass '
                                       'window), --enable / --disable, --emit (a block by hand from a run folder); never '
                                       'publishes, never writes to Amazon')
    gr.add_argument('--asin', required=True)
    what = gr.add_mutually_exclusive_group(required=True)
    what.add_argument('--anchor', action='store_true', help='compute growth.anchor and growth.next_pass and write them')
    what.add_argument('--enable', action='store_true', help='growth.enabled true: the weekly run raises its listing passes')
    what.add_argument('--disable', action='store_true', help='growth.enabled false')
    what.add_argument('--emit', action='store_true', help='a fresh block by hand (trigger manual) from --run, merged into '
                                                          'the product file and written to <run>/growth.json')
    gr.add_argument('--run', help='--emit: the run folder (plan.json, listing.json; item_statuses.json when saved)')
    gr.add_argument('--clicks-daily', help="--anchor: the product's daily ad clicks (<run>/clicks_daily.json), for the "
                                           'first ad click')
    gr.add_argument('--date', help='--anchor: YYYY-MM-DD, the anchor set by hand (with --source hand); --enable: the '
                    'switch date stored as growth.enabled_on (default today in Singapore)')
    gr.add_argument('--source', choices=['hand'], help='--anchor: hand, with --date')
    gr.add_argument('--trigger', choices=['manual'], default='manual', help='--emit: always manual (a block by hand)')
    gr.add_argument('--by', help='who did it, for the activity line and the item history (default: PPC_DASHBOARD_BY or '
                                 'PUBLISHER_NAME)')
    gr.add_argument('--data', help='shared data folder (default: config.json data_dir, else <skill>/data)')
    gr.add_argument('--dry-run', action='store_true', help='print what it would do, write nothing')
    gr.set_defaults(fn=cmd_growth)
    applied = sub.add_parser('applied', help="record that a run's payload folder went out (payloads/applied_rows.json), and "
                                             "lock the rows applied from approved/; never writes to Amazon")
    applied.add_argument('--asin', required=True)
    applied.add_argument('--run', required=True, help='the run folder whose payloads were applied')
    applied.add_argument('--folder', required=True, choices=APPLY_FOLDERS, help='the folder that went out (never held)')
    applied.add_argument('--date', help='YYYY-MM-DD the folder went out, Singapore time (default: today in Singapore)')
    applied.add_argument('--data', help='shared data folder (default: config.json data_dir, else <skill>/data)')
    applied.add_argument('--dry-run', action='store_true', help='work it out and print it, write nothing: the check to run '
                                                               'before any folder is applied, on any day')
    applied.add_argument('--now', help='ISO time in UTC, for deterministic --dry-run checks (default: now)')
    applied.add_argument('--rows', nargs='+', metavar='ROW_IDS',
                         help='only part of the folder went out: record just these rows (row ids from its rows.json, '
                              'separated by commas; quote the list); the rest stays unrecorded')
    applied.add_argument('--record-anyway', action='store_true',
                         help='only when the folder already went out through MAP: record it although the checks that run '
                              'before an apply (its --dry-run) would refuse')
    applied.set_defaults(fn=cmd_applied)
    p = sub.add_parser('publish')
    p.add_argument('--asin', required=True)
    p.add_argument('--run', required=True, help='run folder with plan.json (and applied.json if the apply deviated)')
    p.add_argument('--state', required=True, choices=['applied', 'proposed'])
    p.add_argument('--label')
    p.add_argument('--date', help='YYYY-MM-DD of the run; default today in Singapore')
    p.add_argument('--by', help='who published, shown on the page (default: PPC_DASHBOARD_BY or PUBLISHER_NAME; a personal token overrides it)')
    p.add_argument('--data', help='shared data folder (default: config.json data_dir, else <skill>/data)')
    p.add_argument('--due-plan', help='a later plan.json whose invest bids show as "fix due next run"')
    p.add_argument('--out', help='also write the doc to this file')
    p.add_argument('--dry-run', action='store_true', help='build only, do not publish')
    p.add_argument('--force', action='store_true', help='publish even if someone else published the page since your product file saw it')
    p.set_defaults(fn=cmd_publish)
    q = sub.add_parser('lineup', help='publish a queued product (still on Scale Insights rules) from its product file')
    q.add_argument('--asin', required=True)
    q.add_argument('--date', help='YYYY-MM-DD; default today')
    q.add_argument('--by')
    q.add_argument('--data', help='shared data folder (default: config.json data_dir, else <skill>/data)')
    q.add_argument('--out', help='also write the doc to this file')
    q.add_argument('--dry-run', action='store_true')
    q.add_argument('--force', action='store_true', help='publish even if someone else published the page since your product file saw it')
    q.set_defaults(fn=cmd_lineup)
    f = sub.add_parser('refresh', help='republish a page from the product file, keeping the latest run from the live page')
    f.add_argument('--asin', required=True)
    f.add_argument('--note', help='one line for the activity feed: what changed')
    f.add_argument('--run', help="an AI-managed product's run folder: the product file also records its SQP totals (sqp_history) "
                                 'and data stage (data_stage)')
    f.add_argument('--by')
    f.add_argument('--data', help='shared data folder (default: config.json data_dir, else <skill>/data)')
    f.add_argument('--out', help='also write the doc to this file')
    f.add_argument('--dry-run', action='store_true')
    f.add_argument('--force', action='store_true', help='publish even if someone else published the page since your product file saw it')
    f.set_defaults(fn=cmd_refresh)
    c = sub.add_parser('claim', help='tell the team you are working on a product (one person per product)')
    c.add_argument('--asin', required=True)
    c.add_argument('--what', required=True, help='e.g. "Weekly run", "Onboarding", "Negative audit"')
    c.add_argument('--until', help='YYYY-MM-DD; without it the claim counts as stale after 7 days')
    c.add_argument('--by')
    c.add_argument('--force', action='store_true', help='take over a product someone else has claimed')
    c.set_defaults(fn=cmd_claim)
    r = sub.add_parser('release', help='finish working on a product')
    r.add_argument('--asin', required=True)
    r.add_argument('--note', help='one line on what was done, shown in the activity feed')
    r.add_argument('--by')
    r.set_defaults(fn=cmd_release)
    n = sub.add_parser('note', help='add a line to the activity feed')
    n.add_argument('--text', required=True)
    n.add_argument('--asin')
    n.add_argument('--by')
    n.set_defaults(fn=cmd_note)
    t = sub.add_parser('team', help='who is working on what, and recent activity')
    t.add_argument('--asin')
    t.add_argument('--limit', type=int, default=20)
    t.set_defaults(fn=cmd_team)
    k = sub.add_parser('rank', help='store daily organic rank from Rank Radar pages in the product file, then refresh the page')
    k.add_argument('--asin', required=True)
    k.add_argument('--radar', required=True, nargs='+', help='saved get_rank_radar_data pages (globs allowed)')
    k.add_argument('--days', type=int, default=30, help='days shown, ending on the latest reading (default 30)')
    k.add_argument('--top', type=int, default=12, help='how many searches: invest searches first, then the biggest relevant ones')
    k.add_argument('--note')
    k.add_argument('--by')
    k.add_argument('--data', help='shared data folder (default: config.json data_dir, else <skill>/data)')
    k.add_argument('--out')
    k.add_argument('--dry-run', action='store_true')
    k.add_argument('--force', action='store_true')
    k.set_defaults(fn=cmd_rank)
    lg = sub.add_parser('logs', help='publish the run logs (logs/*.md) to the dashboard: /logs lists them, /api/logs/<name> serves each')
    lg.add_argument('--push', nargs='*', metavar='PATH', help='files or globs to publish (default: every logs/*.md at the repository root)')
    lg.add_argument('--list', action='store_true', help='show what the dashboard holds; push nothing')
    lg.add_argument('--dry-run', action='store_true')
    lg.add_argument('--by')
    lg.set_defaults(fn=cmd_logs)
    sub.add_parser('site').set_defaults(fn=cmd_site)
    li = sub.add_parser('login', help='sign this laptop in with your dashboard account (you type the password yourself)')
    li.add_argument('--email')
    li.add_argument('--label', help='what the Users page calls this laptop (default: <user> on <computer>)')
    li.set_defaults(fn=cmd_login)
    sub.add_parser('logout', help="end this laptop's key and remove it").set_defaults(fn=cmd_logout)
    us = sub.add_parser('users', help="the dashboard's accounts (admins; the first admin with a personal key)")
    usub = us.add_subparsers(dest='users_cmd', required=True)
    usub.add_parser('list')
    ua = usub.add_parser('add')
    ua.add_argument('--email', required=True)
    ua.add_argument('--name', required=True, help='the name the page records on approvals (use the same one as before)')
    ua.add_argument('--role', required=True, choices=['admin', 'ppc', 'growth'])
    us.set_defaults(fn=cmd_users)
    sub.add_parser('list').set_defaults(fn=cmd_list)
    s = sub.add_parser('secrets')
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument('--init', action='store_true', help='run owner: create the team password and the shared publish token')
    g.add_argument('--hashes', action='store_true', help='print the hashes for Railway, and your PUBLISHERS entry')
    g.add_argument('--personal', metavar='NAME', help='teammate: create your own publish token; prints the PUBLISHERS entry')
    s.add_argument('--role', choices=['publisher', 'growth'], default='publisher',
                   help='with --personal: growth makes a For Growth key for a Growth member (status clicks only), saved '
                        'with ROLE=growth in growth-<name>.env beside the secrets file; prints the GROWTH_PUBLISHERS '
                        'entry. Kim and Lee are refused (approver names)')
    s.add_argument('--force', action='store_true')
    s.set_defaults(fn=cmd_secrets)
    a = ap.parse_args()
    if getattr(a, 'by', 'unset') is None and a.cmd in ('publish', 'lineup', 'refresh', 'rank'):
        a.by = default_by()
    a.fn(a)


if __name__ == '__main__':
    main()
