#!/usr/bin/env python3
"""Per-ASIN plan for AI-managed Amazon PPC (YourBrand). One ASIN per run.

Computes, from saved raw pulls, the role and bid of every search and keyword, the change list in
launch order, MAP-ready payloads, the harvest settings and the re-rank cost. Deterministic: two
teammates with the same inputs get the same plan. Nothing here writes to Amazon.

Usage:
  python plan.py --asin B0SAMP0001 --run <run_dir> [--mode weekly|onboard] [--skill <skill_dir>] [--no-reviews "<why>"]
                 [--partial-inventory "<why>"] [--accept-unowned "<why>"]

Run folder inputs (see references/data-pull.md for the exact MCP calls):
  sqp*.json|txt          SI get_search_query_data pages (90 days, raw)            required
  st*.json|txt           SI get_search_term_performance pages (90 days, raw)      required
  kw*.json|txt           SI get_keyword_performance pages (90 days, raw)          required
  suggested_bids.json    {"search": [low, median, high]} from MAP bid recs        required for invest searches
  suggested_bids_business.json  the same, read in the B2B ad group named by need_suggested_bids_business.json
                         required for business (B2B) invest searches
  bid_sources_tried.json {"amazon": "...", "soldscope": "..."}: Amazon was tried for the missing suggestions; the planner
                         prices those searches itself (bid_fallback.py, decision 106)         optional
  soldscope_bids.json    {"search": [cpcMin, cpc, cpcMax]} SoldScope estimates, read after Amazon     optional
  campaigns.json         MAP list_resources sp_campaigns (name_filter=ASIN, ALL)  required (the live reads go by its campaign ids)
  live_keywords_p*.json  MAP list_resources sp_keywords by campaign id (ENABLED,PAUSED, every page)       required (decision 135)
  live_targets_p*.json   MAP list_resources sp_targets by campaign id (ENABLED,PAUSED, every page)        required (decision 135)
  sd_targets_p*.json     SI get_target_performance ad_type SD pages (90 days, raw)                          required with targets.sd
  sd_campaigns*.json     MAP list_resources sd_campaigns for the campaign ids the SD targets name            required with targets.sd
                         Missing live reads stop the run with need_live_inventory.json naming them, unless --partial-inventory
                         "<why>" plans without them (summary.inventory records why): every keyword and target is priced,
                         leaving none behind (Kim, 2026-10-25, decision 135; references/data-pull.md, "Live inventory")
  live_ad_groups_p*.json MAP list_resources sp_ad_groups by campaign id (ENABLED,PAUSED): ad-group default bids (decision 155)
  shared_campaigns.json  MAP list_resources sp_campaigns by the ids the product file's shared_campaigns lists (decision 155)
  sb_targets_p*.json     MAP list_resources sb_targets by the ids need_sb_keywords.json lists (decision 155)
  ad_campaigns_p*.json   MAP run_report_sql "Campaigns by product ad" (SP, SD; 90 days): the campaigns the ASIN's own ads
                         serve in, with every ASIN they advertise (decision 156; required with inventory.ad_campaigns).
                         Single-ASIN ones named without the ASIN join the product; multi-ASIN ones are left out and listed
  own_campaigns.json     MAP list_resources sp_campaigns by the ids of those own campaigns (state ALL)        decision 156
  live_sd_targets_p*.json  MAP list_resources sd_targets by the product's single-ASIN SD campaign ids         decision 156
  sb_themes_p*.json      MAP list_resources sb_themes by the ids need_sb_keywords.json lists (decision 156, sb_video.themes)
                         With coverage.stop_on_missing_reads a live read the ledger needs and the run lacks stops it
                         The coverage ledger (coverage.py, decision 155) gives every live entity one owner; an unowned one
                         stops the run unless --accept-unowned "<why>" (summary.coverage, coverage.json)
  recent_kw.json         MAP run_report_sql: last 2 days keyword spend            recommended
  rank_check.json        {"search": {"since", "rank_then", "rank_now", ...}}      optional (stop-loss)
  sb_campaigns*.json     MAP list_resources sb_campaigns (name_filter=ASIN, ENABLED,PAUSED, every page)   Sponsored Brands video
  sb_keywords_p*.json    MAP list_resources sb_keywords campaign_id=<comma-separated ids of the product's consumer SB campaigns>,
                         every page (need_sb_keywords.json lists the id groups)                            Sponsored Brands video
  sb_kw_perf.json        MAP run_report_sql over sponsored_brands_keywords, 90 days, the product's SB campaigns (references/data-pull.md)
  soldscope_volume.json  {"search": monthly searches}: band clicks for invest searches SQP has no clicks for   optional (lanes)
  inventory_cover.json   {"cover_days": n}: 14 days or fewer is an inventory alert; Auto changes continue   optional (lanes)
  price_change.json      {"days_since": n}: a price change under 14 days ago does the same                    optional (lanes)
  reviews.json           the dashboard's decisions, saved by `dashboard.py reviews --save <run>/reviews.json` as
                         {asin, saved_at, entries}: every decline becomes a lock (B2). Required whenever the product file
                         holds a bids item, whatever its status (C5); refused when it is for another ASIN, or was saved
                         more than a day before the run (C6). --no-reviews "<reason>" plans without it, every change
                         then going to a person, except the rows the planner holds anyway (monitor), which stay in held/
  visibility_inputs.json the live keyword inventory, delivery, contextual recommendations and experiments for the
                         delivery-aware visibility review (references/visibility.md)                        optional
  niche_keywords.json    DataDive get_niche_keywords for the product's niche: the "unlisted" head-term flag reads it    optional (stage early)
  listing.json           the live listing, {asin, read_at, source, title, highlight, bullets, backend}: what the For Growth
                         item checks the copy against (growth.py); without it the item is weave-ins only     optional (For Growth)
  listing_size_verification.json + its raw_listing_file: dated, verbatim live product-size evidence required to
                         release wrong-size positive-keyword pauses (references/live-size-pauses.md)          conditional
  clicks_daily.json      {asin, since, through, source, rows: [{date, clicks}]}, the product's daily ad clicks: the For
                         Growth anchor's first ad click, when the product file holds no growth.anchor          optional (For Growth)

Outputs (in the run folder): plan.json, terms.csv, changes.csv, checks.json, sqp_totals.json (this run's SQP totals, which
dashboard.py appends to the product file's sqp_history), growth.json (the For Growth step of the run, plan_growth: written
on every run, for dashboard.py to store and for Growth's growth_block.py to read), visibility_review.json and
need_visibility_data.json (when config.json visibility.enabled), payload_manifest.json (the current payload files and their
hashes; a re-plan moves the earlier plan's payloads to payload_archive/<SGT time>/), and the payloads split by lane:
payloads/auto/*.json (applied by the run itself during the audit on any day, with no approval: autonomous
runs, Kim 2026-10-22, decision 98) and payloads/review/*.json (after a person approves). auto.enabled is true in
config.json for every AI product since 2026-10-22; in shadow (a product file's "auto": {"enabled": false}, its kill
switch) review/ holds every row the planner would send out and auto/ none. Rows the planner holds (monitor) and rows a
person's decision or a rank experiment holds go to payloads/held/ only, in both modes: held/ is never applied. Each
folder's rows.json names the row_id behind every payload row, and a folder's Scale Insights rows are a checklist for the
browser step, scale_insights_steps.json. The lanes themselves are worked out in plan_lanes.py (section 6); the
stop-loss step-downs in stop_loss.py; the program total's other products in autonomy.py.
Exit code 2 with need_suggested_bids.json when invest searches have no Amazon suggested bid yet, and with
need_suggested_bids_business.json (each search with its B2B campaign and ad group) when business invest searches have
none, until bid_sources_tried.json says Amazon was tried: then the searches still without one are priced by bid_fallback.py
(SoldScope, then an estimate, then the no-suggestion bid) and the run goes on (Kim, 2026-10-23, decision 106). A run folder that went out (payloads/applied_rows.json) or whose approvals were handed out
(payloads/approved/rows.json) is never planned again: plan in a new run folder (C8).
Sponsored Brands video is planned only when the sb_* files are there; need_sb_keywords.json lists the campaign ids still to
read (the plan says so in summary.sb_video.status, and the Sponsored Products plan is still written).
A seasonal product (a `season` block or "mode": "harvest" in its product file; season.py, rulebook section 8) is planned by
its phase: rank build (the block's rank searches are the only invest searches, SQP not required), wake and harvest (no
invest), and nothing in its dated-step phases (the run stops and says so). summary.season says which, and a phase switch.
The product's data stage (scripts/stage.py; docs/superpowers/specs/2026-10-21-keyword-selection-by-data-stage-design.md) is
on summary.stage and every term row: a product in stage launch is not planned (build the launch list first), in stage early
the lanes send every promotion to a person until its search has two SQP weeks, the search-term fallback may reach Prove first,
and volume comes from the launch list or SoldScope where SQP has none (at every stage). The head-term flags and the Discovery
cap lift also apply at every stage; otherwise mature is unchanged. In stage early only, a week whose SQP added more of our
clicks than every earlier week holds every promotion for a person, and --allow-volatile lifts that hold; summary.volatile_week
carries the text at every stage (reported only when mature).
"""
import argparse
import copy
import contextlib
import csv
import datetime as dt
import glob
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import sys
import types
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from close_variants import is_close_variant  # noqa: E402
from human_review import propose as propose_human_review, propose_bids, validate as validate_human_review, sgt_today
import autonomy
import bid_fallback
import evidence
import budget_headroom
import growth
import listing_size
import market_review
import mid_bid
import organic_share
import coverage
import placement_review
import placement_shape
import referral
import blacklist_rescue
import business
import daypart_base
# main() and payload_entries call them by the names they had when they lived here
from business import campaign_rows as business_campaign_rows, stamp_campaigns as stamp_business_campaigns
import plan_lanes
import season
import stage
import stop_loss
import visibility
from searchtext import norm  # noqa: F401  (log_invest.py imports norm from plan)


# ----------------------------------------------------------------------------- helpers
def num(s):
    if s in (None, ''):
        return 0.0
    try:
        return float(str(s).replace('$', '').replace(',', '').replace('%', '').strip() or 0)
    except ValueError:
        return 0.0


def has(term, tok):
    return re.search(r'(^|\s)' + re.escape(tok) + r'($|\s)', term) is not None


def read_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def write_json(path, data, **kw):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, **kw)


def _text_blocks(o):
    return isinstance(o, list) and bool(o) and isinstance(o[0], dict) and 'text' in o[0] and 'type' in o[0]


def unwrap_raw(o):
    """Saved response shapes shared by Claude and Codex (2026-10-23). A dict is an MCP envelope only when it carries
    structuredContent or text blocks under 'content': a payload whose own rows sit under 'content' stays as it is."""
    if isinstance(o, dict):
        if o.get('structuredContent') is not None:
            o = o['structuredContent']
        elif _text_blocks(o.get('content')):
            o = o['content']
    if _text_blocks(o):
        try:
            return json.loads(o[0]['text'])
        except ValueError:
            return o[0]['text']
    return o


def load_raw(path):
    """One saved response: plain JSON, text-block array, or MCP content/structuredContent envelope."""
    with open(path, encoding='utf-8') as fh:
        raw = fh.read().strip()
    return unwrap_raw(json.loads(raw))


def files(run, prefix):
    out = []
    for ext in ('json', 'txt'):
        out += glob.glob(os.path.join(run, f'{prefix}*.{ext}'))
    return sorted(set(out))


def metrics_rows(paths):
    rows = []
    for p in paths:
        t = load_raw(p)
        if isinstance(t, dict) and 'opps' in t:
            rows += [o.get('metrics', {}) for o in t['opps']]
        elif isinstance(t, dict) and 'data' in t:
            rows += t['data']
        elif isinstance(t, list):
            rows += t
    return rows


def r2(x):
    return None if x is None else round(x, 2)


def at_least(value, threshold):
    return value >= threshold or math.isclose(value, threshold, rel_tol=1e-12)


def load_visibility_inputs(run, asin):
    path = os.path.join(run, 'visibility_inputs.json')
    if not os.path.exists(path):
        return {}
    snapshot = load_raw(path)
    if not isinstance(snapshot, dict) or snapshot.get('asin') != asin:
        raise ValueError('visibility_inputs.json must identify this ASIN.')
    for field in ('inventory', 'delivery', 'recommendations', 'experiments'):
        records = snapshot.get(field, [])
        if not isinstance(records, list) or any(not isinstance(row, dict) or row.get('asin') != asin for row in records):
            raise ValueError(f'visibility_inputs.json {field} must contain records for this ASIN only.')
    return snapshot


def merge_keyword_inventory(rows, inputs, asin, as_of, policy, campaigns=None):
    merged = {}
    for row in rows:
        keyword_id = str(row.get('KeywordId') or '')
        if not keyword_id:
            raise ValueError('Keyword report must identify each target.')
        if keyword_id in merged and merged[keyword_id] != row:
            raise ValueError(f'Conflicting keyword report rows for {keyword_id}; reconcile source windows before planning.')
        merged[keyword_id] = dict(row)
    campaign_names = {str(row.get('campaignId')): row.get('name') for row in campaigns or []}
    seen = set()
    for item in inputs.get('inventory', []):
        keyword_id = str(item.get('keyword_id') or '')
        if not keyword_id or keyword_id in seen:
            raise ValueError('Inventory keyword IDs must be present and unique.')
        seen.add(keyword_id)
        if item.get('ad_product', 'SP') != 'SP' or item.get('match', '').lower() not in ('exact', 'phrase', 'broad'):
            continue
        existing = merged.get(keyword_id)
        identity = {'CampaignId': 'campaign_id', 'AdGroupId': 'ad_group_id', 'Keyword': 'keyword', 'MatchType': 'match'}
        if any(not item.get(field) for field in identity.values()):
            raise ValueError(f'Incomplete inventory identity for {keyword_id}.')
        if existing and any(norm(str(existing.get(field) or '')) != norm(str(item[key])) for field, key in identity.items()):
            raise ValueError(f'Inventory identity differs from keyword report for {keyword_id}.')
        try:
            age = (dt.date.fromisoformat(as_of) - dt.date.fromisoformat(item.get('observed_on', ''))).days
            fresh = 0 <= age <= policy.get('max_snapshot_age_days', 2)
        except (ValueError, TypeError):
            fresh = False
        campaign_name = item.get('campaign') or campaign_names.get(str(item['campaign_id'])) or (existing or {}).get('CampaignName')
        row = existing or dict(KeywordId=keyword_id, ASIN=asin, AdType='SP', Clicks=0, Orders=0, Spend=0, Sales=0, Impressions=0)
        row['CampaignName'] = campaign_name or f'{asin} campaign {item["campaign_id"]}'
        row.update({field: item[key] for field, key in identity.items()})
        row['visibility_inventory'] = item
        row['inventory_only'] = existing is None
        if fresh and num(item.get('current_bid')) > 0:
            row['Bid'] = num(item['current_bid'])
        gates = item.get('gates') or {}
        # only a check that says "no" holds the bid (decision 107, 2026-10-23): a paused campaign, ad group or keyword. A
        # snapshot that is stale or incomplete, or an enabled-state that wasn't read, holds nothing; it is noted on the row
        pause = visibility.scheduled_pause(item, as_of, policy.get('max_snapshot_age_days', 2))
        row['inventory_hold'] = any(gates.get(gate) is False for gate in ('campaign_enabled', 'ad_group_enabled', 'target_enabled')
                                    if gate not in (pause or {}).get('exempt_gates', []))
        row['inventory_unverified'] = [why for why, gap in (
            ('snapshot stale', not fresh), ('no campaign name', not campaign_name),
            ('inventory incomplete', inputs.get('inventory_complete') is not True),
            ('enabled state not read', any(gates.get(gate) not in (True, False) for gate in ('campaign_enabled', 'ad_group_enabled', 'target_enabled'))))
            if gap]
        merged[keyword_id] = row
    return list(merged.values())


# ----------------------------------------------------------------------------- inputs
def load_suggested(run, name):
    """A saved {"search": [low, median, high]} map of Amazon's suggested bids (suggested_bids.json, and
    suggested_bids_business.json for business invest searches), keyed by the normal form of each search; "_" keys are notes."""
    p = os.path.join(run, name)
    return {norm(k): v for k, v in read_json(p).items() if not k.startswith('_')} if os.path.exists(p) else {}


def mid_summary(plan, sb_mid_of, mid_cfg):
    """plan.json's summary.mid_bid (decision 177): the keywords bidding the suggested mid (rows: Sponsored Products, then
    Sponsored Brands), the launch tests that ended this run (ended: 0 orders on 15+ clicks, or 1 order on 30+), the copies
    left at their role's price, and the 90-day spend of each group. None when mid_bid is off."""
    if not mid_cfg:
        return None
    rows = [dict(channel='SP', keyword=p['keyword'], match=p['match'], campaign=p['campaign'], keyword_id=p['keyword_id'],
                 state=p['mid_bid']['state'], clicks90=p['clicks90'], orders90=p['orders90'], spend90=p['spend90'],
                 mid=p['mid_bid']['mid'], source=p['mid_bid']['source'], priced_on=p['mid_bid']['priced_on'],
                 bid=p['bid'], new_bid=p['new_bid'], breakeven=p['breakeven_cpc'])
            for p in plan if p.get('mid_bid')]
    rows += [dict(channel='SB', keyword=r['keyword'], match=r['match'], keyword_id=kid, state=r['state'], clicks90=r['clicks90'],
                  orders90=r['orders90'], spend90=r['spend90'], mid=r['mid'], source=r['source'], priced_on=r['priced_on'],
                  new_bid=r['bid']) for kid, r in sorted(sb_mid_of.items())]
    ended = [dict(keyword=p['keyword'], match=p['match'], campaign=p['campaign'], state=p['mid_state'], clicks90=p['clicks90'],
                  orders90=p['orders90'], spend90=p['spend90'], new_bid=p['new_bid'], action=p['action'])
             for p in plan if p.get('mid_state') in ('failed', 'judged')]
    testing = [r for r in rows if r['state'] in ('testing', 'extended')]
    return dict(rows=rows, ended=ended, copies=sum(1 for p in plan if p.get('mid_state') == 'copy'),
                counts=dict(Counter(r['state'] for r in rows)),
                sources=dict(Counter(r['source'] for r in rows)),
                launch_test_spend90=round(sum(r['spend90'] for r in testing), 2),
                ended_test_spend90=round(sum(r['spend90'] for r in ended), 2),
                validated_spend90=round(sum(r['spend90'] for r in rows if r['state'] == 'validated'), 2))


def load_ad_campaigns(run, asin):
    """The campaigns this product's own ads serve in (Kim, 2026-10-27, decision 156: "check to see if the new skill covers
    every single campaign ... don't leave any out"), from the saved MAP run_report_sql reads ad_campaigns_p*.json
    (references/data-pull.md, "Campaigns by product ad"): one row per Sponsored Products or Sponsored Display campaign that
    advertised the ASIN in the 90 days, with every ASIN it advertised. Until then a campaign was found by its name alone,
    so a campaign of this product named without its ASIN (the "Auto - $0.65 down only" ones) was never priced.

    Returns None when the run has no such read, else dict(own={campaign id: row}: it advertises this ASIN alone and its name
    doesn't carry it, so it joins the product's campaigns; multi={campaign id: row}: it advertises several ASINs, a product
    collection or cross-selling campaign kept that way on purpose (Kim, 2026-10-27), left out of the AI's pricing and
    listed in the coverage ledger; sd: every single-ASIN Sponsored Display campaign, named or not, whose live targets are
    read by id; read=n rows)."""
    fs = files(run, 'ad_campaigns_p')
    if not fs:
        return None
    rows = [r for p in fs for r in load_items(p)]
    own, multi, sd = {}, {}, set()
    for r in rows:
        cid = str(r.get('campaignId') or '')
        asins = sorted({a.strip() for a in str(r.get('asins') or '').split(',') if a.strip()})
        if not cid or asin not in asins:
            continue
        rec = dict(campaign_id=cid, name=r.get('campaignName') or '', ad_type=str(r.get('ad_type') or 'SP').upper(),
                   asins=asins, spend90=round(num(r.get('spend90')), 2))
        if len(asins) > 1:
            multi[cid] = rec
            continue
        if rec['ad_type'] == 'SD':
            sd.add(cid)
        if asin not in rec['name']:
            own[cid] = rec
    return dict(own=own, multi=multi, sd=sd, read=len(rows))


def in_scope(asin, name, cid, scope):
    """Whether a campaign is this product's to price: its name carries the ASIN or its ads show it advertises the ASIN alone
    (load_ad_campaigns), and it is not a multi-ASIN campaign (decision 156)."""
    cid = str(cid or '')
    if scope and cid in scope['multi']:
        return False
    return asin in (name or '') or bool(scope and cid in scope['own'])


def load_inputs(run, asin, cfg, scope=None):
    sq, through = {}, []
    for p in files(run, 'sqp'):
        t = load_raw(p)
        meta = (t.get('Meta') or {}) if isinstance(t, dict) else {}
        try:
            through.append(dt.date.fromisoformat(str(meta.get('data_through'))[:10]))
        except ValueError:
            pass  # a page without a readable date: section 6 treats an undated SQP as stale
        for q in (t.get('Queries') or []) if isinstance(t, dict) else []:
            if q.get('ASIN') and q['ASIN'] != asin:
                continue
            sq[norm(q['Query'])] = q
    st_rows = [m for m in metrics_rows(files(run, 'st')) if (m.get('ASIN') or asin) == asin]
    kw_rows = [m for m in metrics_rows(files(run, 'kw')) if in_scope(asin, m.get('CampaignName'), m.get('CampaignId'), scope)
               and (m.get('AdType') or 'SP') == 'SP']
    sug = load_suggested(run, 'suggested_bids.json')
    camps = []
    p = os.path.join(run, 'campaigns.json')
    if os.path.exists(p):
        t = load_raw(p)
        camps = t.get('items', t) if isinstance(t, dict) else t
        camps = [c for c in camps if in_scope(asin, c.get('name'), c.get('campaignId'), scope)]
    if scope and scope['own']:
        # this product's campaigns named without its ASIN (decision 156), read by id (own_campaigns*.json)
        have = {str(c.get('campaignId')) for c in camps}
        camps = camps + [c for p in files(run, 'own_campaigns') for c in load_items(p)
                         if str(c.get('campaignId')) in scope['own'] and str(c.get('campaignId')) not in have]
    recent = []
    p = os.path.join(run, 'recent_kw.json')
    if os.path.exists(p):
        t = load_raw(p)
        recent = t.get('data', t) if isinstance(t, dict) else t
        recent = [r for r in recent if in_scope(asin, r.get('campaignName'), r.get('campaignId'), scope)]
    rank = {}
    p = os.path.join(run, 'rank_check.json')
    if os.path.exists(p):
        rank = {norm(k): v for k, v in read_json(p).items() if not k.startswith('_')}
    return sq, st_rows, kw_rows, sug, camps, recent, rank, (min(through).isoformat() if through else None)


def load_last_season(run, asin):
    """Last season's SQP for a seasonal product (Kim, 2026-10-30, decision 172: "use last season's sqp"): the Scale Insights
    get_search_query_data pages for the same weeks a year earlier, saved as last_season_sqp_p1.json, _p2 ... (data-pull.md).
    Returns {search: row} and the window the pages say they cover, or ({}, None) without the files. Their name must not start
    with "sqp": files(run, 'sqp') would read them as this year's."""
    rows, through = {}, []
    for p in files(run, 'last_season_sqp'):
        t = load_raw(p)
        meta = (t.get('Meta') or {}) if isinstance(t, dict) else {}
        if meta.get('data_through'):
            through.append(str(meta['data_through'])[:10])
        for q in (t.get('Queries') or []) if isinstance(t, dict) else []:
            if q.get('ASIN') and q['ASIN'] != asin:
                continue
            rows[norm(q['Query'])] = q
    return rows, (max(through) if through else None)


def load_lane_inputs(run):
    """The optional run inputs of the lanes step (plan_lanes.assign); each is None when its file isn't there.

    reviews is reviews.json, the dashboard's decisions as `dashboard.py reviews` saved them: its entries (C6:
    {asin, saved_at, entries}; an older save is the bare list). One that can't be read comes back as something that isn't
    a list, which the lanes step treats as unreadable (every change to a person). plan.py's main() checks its asin and
    saved_at before it gets here."""
    def optional(name):
        p = os.path.join(run, name)
        return load_raw(p) if os.path.exists(p) else None
    ss = optional('soldscope_volume.json')
    try:
        reviews = optional('reviews.json')
    except (OSError, ValueError) as e:
        reviews = f'unreadable: {e}'
    if isinstance(reviews, dict) and 'entries' in reviews:
        reviews = reviews['entries']  # C6's dated shape; entries that aren't a list stay unreadable
    return dict(soldscope={norm(k): v for k, v in ss.items() if not str(k).startswith('_')} if isinstance(ss, dict) else {},
                inventory_cover=optional('inventory_cover.json'), price_change=optional('price_change.json'), reviews=reviews)


def load_targets(run, asin, auto=False, scope=None):
    """Sponsored Products ASIN and category targets of this product (SI get_target_performance pages, pt*.json), and with
    auto its auto targets too (close match, loose match, substitutes, complements; config targets.auto_targets, decision
    135). The tool's asin_list filter returns other products' targets too, so keep only rows whose campaign carries the ASIN."""
    kinds = ('product', 'category', 'auto') if auto else ('product', 'category')
    return [m for m in metrics_rows(files(run, 'pt')) if in_scope(asin, m.get('CampaignName'), m.get('CampaignId'), scope)
            and (m.get('AdType') or 'SP') == 'SP' and (m.get('TargetType') or 'product') in kinds]


# MAP's Sponsored Products auto expressions, by the names Scale Insights reports them under
AUTO_EXPRESSIONS = {'QUERY_HIGH_REL_MATCHES': 'close-match', 'QUERY_BROAD_REL_MATCHES': 'loose-match',
                    'ASIN_SUBSTITUTE_RELATED': 'substitutes', 'ASIN_ACCESSORY_RELATED': 'complements'}


def shared_campaign_list(cfg):
    """The product file's shared_campaigns (decision 155): multi-product campaigns that advertise only AI products, as
    {campaign id: {products, profit_per_unit_min}}. A plain id carries no lowest profit, so it is left out (read as None)."""
    out = {}
    for x in cfg.get('shared_campaigns') or []:
        if isinstance(x, dict) and x.get('campaign_id'):
            out[str(x['campaign_id'])] = dict(products=list(x.get('products') or []),
                                              profit_per_unit_min=x.get('profit_per_unit_min'))
        elif isinstance(x, (str, int)):
            out[str(x)] = dict(products=[], profit_per_unit_min=None)
    return out


def load_shared_campaigns(run, ids):
    """The shared campaigns' live records (shared_campaigns.json: MAP list_resources sp_campaigns by campaign id), the ones
    the product file names."""
    out = []
    for p in files(run, 'shared_campaigns'):
        out += [c for c in load_items(p) if str(c.get('campaignId')) in ids]
    return out


def load_live_inventory(run):
    """The product's live Sponsored Products keywords and targets (MAP list_resources sp_keywords and sp_targets by campaign
    id: live_keywords_p*.json and live_targets_p*.json, references/data-pull.md). The planner prices them beyond the rows
    Scale Insights reports, so a keyword or target with no 90-day row is priced too (config inventory, decision 135)."""
    keywords = [k for p in files(run, 'live_keywords') for k in load_items(p)]
    return dict(keywords=keywords, targets=live_targets([t for p in files(run, 'live_targets') for t in load_items(p)], keywords),
                keywords_read=bool(files(run, 'live_keywords')), targets_read=bool(files(run, 'live_targets')))


def unified_bid(value):
    """A bid as MAP returns it: a number, or in Amazon's unified format an object ({"bid": 0.5, ...} or {"value": ...})."""
    if isinstance(value, dict):
        for key in ('bid', 'value', 'amount', 'defaultBid'):
            if value.get(key) not in (None, ''):
                return value[key]
        return None
    return value


def live_targets(targets, keywords):
    """The live sp_targets read without the keywords MAP returns there too. Amazon mirrors a keyword into the targeting
    clauses under the keyword's own id, and MAP sometimes returns it in the unified format (bid as an object): the keyword
    read owns it (the keyword wins, MAP's report notes), so it is left out here instead of standing as an unowned target
    (2026-11-04: B0SAMP0006 needed --accept-unowned for 2 such ids). A unified bid object on a real target is read as its
    number."""
    keyword_ids = {str(k.get('keywordId')) for k in keywords if k.get('keywordId') is not None}
    out = []
    for t in targets:
        tid = str(t.get('targetId') or t.get('keywordId') or '')
        if tid in keyword_ids or (t.get('keywordId') is not None and t.get('targetId') is None):
            continue
        if isinstance(t.get('bid'), dict):
            t = dict(t, bid=unified_bid(t['bid']), bid_object=t['bid'])
        out.append(t)
    return out


def rebase_live(items, stored, id_key, m):
    """Under a Scale Insights dayparting modifier m (daypart_base.py, decision 150), every live item's bid becomes the base bid
    behind it, in place: its stored bid when the live one is the stored bid x m, else live / m. The bid as read stays in
    live_bid. Returns how many changed."""
    n = 0
    for it in items:
        if m == 1.0 or it.get('bid') in (None, ''):
            continue
        live = num(it['bid'])
        b = daypart_base.base(stored.get(str(it.get(id_key))), live, m)
        it['live_bid'], it['bid'] = live, b
        n += b != live
    return n


def merge_live_keywords(rows, live, camps, asin, paused=False):
    """Every enabled keyword of the product's enabled campaigns joins the plan (decision 135). A live keyword with no 90-day
    row joins with no clicks (live_only), and a row Scale Insights reports takes its live bid. A keyword the live read shows
    paused is kept, never priced (inventory_hold). A keyword of a campaign that isn't this product's, or with no bid of its
    own (it bids its ad group's default), is left out and counted. A Scale Insights row the live read (enabled and paused
    keywords) doesn't hold, in a campaign the read did cover (it holds other keywords of it), is archived or gone: it is
    kept, never priced (inventory_hold, not_live), because Amazon refuses a write to it (2026-10-26, B0SAMP0033: 2 archived
    keywords priced from their 90-day rows were refused). With paused (inventory.paused, decision 155) a paused live keyword with no 90-day row joins too,
    held (inventory_hold), so its price can be written as a cut. Returns (rows, counts)."""
    by_camp = {str(c.get('campaignId')): c for c in camps}
    merged = {str(r.get('KeywordId')): r for r in rows}
    counts = Counter()
    seen = {str(k.get('keywordId') or '') for k in live}
    covered = {str(k.get('campaignId')) for k in live}
    for kid, row in merged.items():
        if kid not in seen and str(row.get('CampaignId')) in covered and str(row.get('CampaignId')) in by_camp:
            row['inventory_hold'] = row['not_live'] = True
            counts['not_live'] += 1
    for k in live:
        kid, camp = str(k.get('keywordId') or ''), by_camp.get(str(k.get('campaignId')))
        if not kid or camp is None:
            counts['other_campaign'] += 1
            continue
        state, bid, row = (k.get('state') or '').upper(), k.get('bid'), merged.get(kid)
        if row is not None:
            if bid not in (None, ''):
                row['Bid'] = num(bid)
            if state and state != 'ENABLED':
                row['inventory_hold'] = True
            counts['refreshed'] += 1
        elif (state != 'ENABLED' or (camp.get('state') or '').upper() != 'ENABLED') and not (paused and bid not in (None, '')):
            counts['not_enabled'] += 1
        elif bid in (None, ''):
            counts['no_bid'] += 1
        else:
            held = state != 'ENABLED' or (camp.get('state') or '').upper() != 'ENABLED'
            merged[kid] = dict(KeywordId=kid, ASIN=asin, AdType='SP', CampaignId=str(k.get('campaignId')),
                               AdGroupId=str(k.get('adGroupId')), CampaignName=camp.get('name'), Keyword=k.get('keywordText') or '',
                               MatchType=(k.get('matchType') or '').lower(), Bid=num(bid), Clicks=0, Orders=0, Spend=0,
                               Sales=0, Impressions=0, inventory_only=True, live_only=True, **(dict(inventory_hold=True) if held else {}))
            counts['paused_added' if held else 'added'] += 1
    return list(merged.values()), dict(counts)


def live_target_text(t):
    """A live Sponsored Products target's (TargetType, TargetText), named the way Scale Insights names them."""
    expr = t.get('expression') or t.get('resolvedExpression') or []
    first = expr[0] if expr and isinstance(expr[0], dict) else {}
    kind = str(first.get('type') or '').upper()
    if (t.get('expressionType') or '').upper() == 'AUTO' or kind in AUTO_EXPRESSIONS:
        return 'auto', AUTO_EXPRESSIONS.get(kind, kind.lower())
    return ('category' if 'CATEGORY' in kind else 'product'), str(first.get('value') or kind.lower())


def merge_live_targets(rows, live, camps, auto, paused=False):
    """The product's live Sponsored Products targets join its target rows as merge_live_keywords does for keywords: a live
    target with no 90-day row joins with no clicks, a reported row takes its live bid, a paused one is never priced. Auto
    targets only with auto. Returns (rows, counts)."""
    by_camp = {str(c.get('campaignId')): c for c in camps}
    merged = {str(r.get('TargetId')): r for r in rows}
    counts = Counter()
    for t in live:
        tid, camp = str(t.get('targetId') or ''), by_camp.get(str(t.get('campaignId')))
        if not tid or camp is None:
            counts['other_campaign'] += 1
            continue
        ttype, text = live_target_text(t)
        if ttype == 'auto' and not auto:
            continue
        state, bid, row = (t.get('state') or '').upper(), t.get('bid'), merged.get(tid)
        if row is not None:
            if bid not in (None, ''):
                row['Bid'] = num(bid)
            if state and state != 'ENABLED':
                row['inventory_hold'] = True
            counts['refreshed'] += 1
        elif (state != 'ENABLED' or (camp.get('state') or '').upper() != 'ENABLED') and not (paused and bid not in (None, '')):
            counts['not_enabled'] += 1
        elif bid in (None, ''):
            counts['no_bid'] += 1
        else:
            held = state != 'ENABLED' or (camp.get('state') or '').upper() != 'ENABLED'
            merged[tid] = dict(TargetId=tid, AdType='SP', TargetType=ttype, TargetText=text, CampaignId=str(t.get('campaignId')),
                               AdGroupId=str(t.get('adGroupId')), CampaignName=camp.get('name'), Bid=num(bid), Clicks=0,
                               Orders=0, Spend=0, Sales=0, live_only=True, **(dict(inventory_hold=True) if held else {}))
            counts['paused_added' if held else 'added'] += 1
    return list(merged.values()), dict(counts)


def load_sd_targets(run, asin, skip_cost_types=('vcpm',), scope=None):
    """This product's Sponsored Display targets (SI get_target_performance ad_type SD pages, sd_targets_p*.json; decision
    135), each with its campaign's live state and cost type (MAP list_resources sd_campaigns by campaign id,
    sd_campaigns*.json). Only rows whose campaign carries the ASIN, is enabled and bids per click: a vCPM campaign's bid is
    per thousand impressions, so it is never priced like a click. Returns (rows, status, campaign ids still to read).

    Since decision 156 the live targets of the product's single-ASIN SD campaigns (live_sd_targets_p*.json: MAP
    list_resources sd_targets by campaign id) join too: one with no 90-day row joins with no clicks (live_only), so it is
    capped and never raised, as a Sponsored Products one is; a paused one is held (priced cut only with targets.paused)."""
    rows = [m for m in metrics_rows(files(run, 'sd_targets')) if in_scope(asin, m.get('CampaignName'), m.get('CampaignId'), scope)
            and (m.get('AdType') or 'SD') == 'SD']
    if not files(run, 'sd_targets'):
        return [], 'not pulled: no sd_targets_p*.json in the run folder', []
    camps = {str(c.get('campaignId')): c for p in files(run, 'sd_campaigns') for c in load_items(p)}
    by_id = {str(m.get('TargetId')): m for m in rows}
    sd_ids = set((scope or {}).get('sd') or ())
    for t in (t for p in files(run, 'live_sd_targets') for t in load_items(p)):
        tid, cid = str(t.get('targetId') or ''), str(t.get('campaignId') or '')
        if not tid or cid not in sd_ids | {str(m.get('CampaignId')) for m in rows}:
            continue
        state = (t.get('state') or '').lower()
        if state not in ('enabled', 'paused') or t.get('bid') in (None, ''):
            continue
        if tid in by_id:
            by_id[tid]['Bid'] = num(t['bid'])
            if state == 'paused':
                by_id[tid]['inventory_hold'] = True
            continue
        text = ', '.join(f"{e.get('type')}={e.get('value')}" if e.get('value') else str(e.get('type'))
                         for e in (t.get('expression') or t.get('resolvedExpression') or []) if isinstance(e, dict))
        row = dict(TargetId=tid, AdType='SD', TargetType='sd', TargetText=text or tid, CampaignId=cid,
                   AdGroupId=str(t.get('adGroupId')), CampaignName=(camps.get(cid) or {}).get('name') or ((scope or {}).get('own', {}).get(cid) or {}).get('name') or '',
                   Bid=num(t['bid']), Clicks=0, Orders=0, Spend=0, Sales=0, live_only=True,
                   **(dict(inventory_hold=True) if state == 'paused' else {}))
        rows.append(row)
        by_id[tid] = row
    missing = sorted(({str(m.get('CampaignId')) for m in rows} | sd_ids) - set(camps))
    kept = []
    skipped = Counter()
    for m in rows:
        c = camps.get(str(m.get('CampaignId')))
        if c is None:
            skipped['campaign not read'] += 1
        elif (c.get('state') or '').lower() != 'enabled':
            skipped['campaign not enabled'] += 1
        elif (c.get('costType') or 'cpc').lower() in skip_cost_types:
            skipped[f"{(c.get('costType') or '').lower()} campaign"] += 1
        else:
            kept.append(dict(m, AdType='SD'))
    status = 'ok' if not missing else f'{len(missing)} SD campaigns not read yet: see need_live_inventory.json'
    if skipped:
        status += '; left out: ' + ', '.join(f'{n} ({why})' for why, n in sorted(skipped.items()))
    return kept, status, missing


def load_items(path):
    """A saved list_resources response (raw, or the tool-result wrapper): its items."""
    t = load_raw(path)
    if isinstance(t, dict):
        return t.get('items') or t.get('data') or []
    return t if isinstance(t, list) else []


def load_sb(run, asin, multi_markers=()):
    """Sponsored Brands inputs for the video build: this ASIN's SB campaigns, the keywords of its video campaigns
    (read by campaign id: the account-wide keyword-text filter misses keywords), and 90-day results by keyword id."""
    camps, multi = {}, {}
    for p in files(run, 'sb_campaigns'):
        for c in load_items(p):
            if asin in (c.get('name') or ''):
                # a product collection or store spotlight ad features several ASINs on purpose (Kim, 2026-10-27, decision
                # 156): left out of the AI's pricing and listed in the coverage ledger
                if any(m.lower() in (c.get('name') or '').lower() for m in multi_markers):
                    multi[str(c.get('campaignId'))] = c
                else:
                    camps[str(c.get('campaignId'))] = c
    kws, read_ids = {}, set()
    for p in files(run, 'sb_keywords'):
        for k in load_items(p):
            if str(k.get('campaignId')) in camps:
                kws[str(k.get('keywordId'))] = k
                read_ids.add(str(k.get('campaignId')))
    # the product and category targets of those campaigns (sb_targets_p*.json, decision 155): priced like the keywords, their
    # 90-day results in the same keyword report (on a target's row the report's keywordId is the targetId)
    tgts = {}
    for p in files(run, 'sb_targets'):
        for t in load_items(p):
            if str(t.get('campaignId')) in camps:
                tgts[str(t.get('targetId'))] = t
    # their theme targets (sb_themes_p*.json, decision 156): Amazon-managed keyword groups ("keywords related to your brand",
    # "... to your landing pages") bid as one unit; their results are the keyword report's THEME rows (keywordId = themeId)
    themes = {}
    for p in files(run, 'sb_themes'):
        for t in load_items(p):
            if str(t.get('campaignId')) in camps:
                themes[str(t.get('themeId'))] = t
    cover = defaultdict(list)
    for k in kws.values():
        cover[norm(k.get('keywordText'))].append(k)
    perf = {}
    p = os.path.join(run, 'sb_kw_perf.json')
    if os.path.exists(p):
        t = load_raw(p)
        for r in (t.get('data') or t.get('rows') or []) if isinstance(t, dict) else (t or []):
            perf[str(r.get('keywordId'))] = r
    return dict(campaigns=camps, multi=multi, keywords=list(kws.values()), cover=cover, pulled=bool(files(run, 'sb_keywords')), read_ids=read_ids,
                perf=perf, targets=list(tgts.values()), targets_pulled=bool(files(run, 'sb_targets')),
                themes=list(themes.values()), themes_pulled=bool(files(run, 'sb_themes')))


def load_radar(run):
    """DataDive get_rank_radar_data pages saved as radar*.json: {keyword: [(date, organicRank), ...]}. 101 = not in top 100."""
    out = {}
    for p in files(run, 'radar'):
        t = load_raw(p)
        lst = None
        if isinstance(t, dict):
            for k in ('keywords', 'data', 'items', 'results', 'rows'):
                if isinstance(t.get(k), list):
                    lst = t[k]
                    break
        elif isinstance(t, list):
            lst = t
        for kw in lst or []:
            if isinstance(kw, dict) and kw.get('keyword') and isinstance(kw.get('ranks'), list):
                out[norm(kw['keyword'])] = sorted((str(r.get('date'))[:10], r.get('organicRank')) for r in kw['ranks'] if r.get('date'))
    return out


def _asin_input(run, name, asin, what):
    """<run>/<name> when it is there, else None. A file for another ASIN stops the run, worded as reviews.json's check."""
    path = os.path.join(run, name)
    if not os.path.exists(path):
        return None
    data = load_raw(path)
    held = data.get('asin') if isinstance(data, dict) else None
    if held != asin:
        sys.exit(f'{path} holds {what} for {held!r}, not {asin}: pull it again for {asin} (references/data-pull.md). '
                 'Nothing planned.')
    return data


def load_listing(run, asin):
    """<run>/listing.json, the live listing the For Growth item checks the copy against (growth.py): {asin, read_at,
    source, title, highlight, bullets: [..], backend: str | None}. None when the run read no listing: the item is then
    weave-ins only, every In row sitting today as unknown.

    The shape is checked (open item 51a, 2026-10-25): a `bullets` string is read as one bullet, a `highlight` or
    `backend` list of strings, or of raw attribute dicts `{value, ...}`, is joined into one text; any other field of the
    wrong type makes the listing unread (None, with a warning on stderr), because a wrong shape would read every In row
    as missing from the copy and hand Growth a false block."""
    data = _asin_input(run, 'listing.json', asin, 'the listing')
    if data is None:
        return None
    data = dict(data)
    if isinstance(data.get('bullets'), str):
        data['bullets'] = [data['bullets']]
    # the raw attribute shape (2026-10-25): title_differentiation and generic_keyword come from MarketplaceAdPros as a
    # list of values; a list of strings is one text. 13 of the 32 hand blocks of 2026-10-25 were built blind because of it.
    # Each item is a string, or the raw attribute dict {value, language_tag, marketplace_id} (the shape in 11 run folders
    # of 2026-10-25, which the first fix of that day missed).
    def _values(items):
        out = [x.get('value') if isinstance(x, dict) else x for x in items]
        return out if all(isinstance(x, str) for x in out) else None
    for k in ('highlight', 'backend'):
        values = _values(data[k]) if isinstance(data.get(k), list) and data[k] else None
        if values is not None:
            data[k] = ' '.join(x.strip() for x in values if x.strip()) or None
    if isinstance(data.get('bullets'), list) and data['bullets'] and _values(data['bullets']) is not None:
        data['bullets'] = [x for x in _values(data['bullets']) if x.strip()]
    wrong = [k for k in ('title', 'highlight', 'backend') if data.get(k) is not None and not isinstance(data[k], str)]
    bullets = data.get('bullets')
    if bullets is not None and not (isinstance(bullets, list) and all(isinstance(b, str) for b in bullets)):
        wrong.append('bullets')
    if wrong:
        print(f"warning: {os.path.join(run, 'listing.json')} has the wrong shape ({', '.join(wrong)}): read as no "
              'listing this run; pull it again (references/data-pull.md)', file=sys.stderr)
        return None
    return data


def load_clicks_daily(run, asin):
    """<run>/clicks_daily.json, the product's daily ad clicks: {asin, since, through, source, rows: [{date, clicks}]}. The
    For Growth anchor reads its first ad click from it when the product file holds no growth.anchor. None when not pulled."""
    return _asin_input(run, 'clicks_daily.json', asin, 'the click series')


def checkpoint_days(months):
    """The day of investing a stop-loss checkpoint falls on: month 3 is day 91, 6 day 182, 9 day 274, 12 day 365."""
    return round(months * 365 / 12)


def median_rank(series, start=None, end=None):
    vals = [r for d, r in series if r is not None and (start is None or d >= start) and (end is None or d <= end)]
    return statistics.median(vals) if vals else None


# ----------------------------------------------------------------------------- relevance
def dimension_pairs(text):
    """Order-free dimensions in inches; accept decimals, spaces, x/× and inch suffixes."""
    number = r'(\d+(?:\.\d+)?)'
    inch = r'(?:inches|inch|in\b|["″])?'
    pattern = rf'(?<![\w.]){number}\s*{inch}\s*[x×]\s*{number}\s*{inch}(?!\d|\.\d)'
    return {tuple(sorted((float(a), float(b)))) for a, b in re.findall(pattern, str(text or ''), re.I)}


def own_sizes(asin, cfg):
    """The product's size, else its negative-audit fingerprint's size."""
    sizes = dimension_pairs(cfg.get('size'))
    if sizes:
        return sizes
    path = os.path.join(HERE, '..', '..', 'amazon-negative-keyword-audit', 'data', 'fingerprints.json')
    fingerprint = (read_json(path).get(asin) or {}) if os.path.exists(path) else {}
    return dimension_pairs(fingerprint.get('size'))


def protected_sizes(cfg):
    """Sizes the team protects on purpose: a protect entry naming a size (Get Well's '5x7', whose 5x7 searches convert,
    logs/2026-10-23-get-well-cards-onboarding-preflight.md) is a decision; a generic phrase ('thank you') is not."""
    return dimension_pairs(' | '.join((cfg.get('relevance') or {}).get('protect') or []))


def product_sizes(asin, cfg):
    """Read once per plan: the sizes a search may name, its own plus the protected ones. Empty when its own is unknown."""
    own = own_sizes(asin, cfg)
    return own | protected_sizes(cfg) if own else set()


def size_text(sizes):
    return ', '.join(f'{a:g}x{b:g}' for a, b in sorted(sizes))


def wrong_size(term, sizes):
    other = dimension_pairs(term) - set(map(tuple, sizes)) if sizes else set()
    return f'Wrong size: search names {size_text(other)}; sizes allowed for this product: {size_text(sizes)} inches.' if other else None


def size_holds(changes, sizes, verification=None):
    """Only a verified live-listing relevance pause or an ordinary bid cut escapes the size hold.

    A fingerprint alone still cannot authorize a pause. A confirmed positive-keyword pause follows normal lanes,
    including human locks, stale data, ownership and Auto-off; promotions, routing and negatives gain no exception.
    """
    for row in changes:
        row.pop(listing_size.MARKER, None)
        mismatch = wrong_size(row.get('keyword'), sizes)
        bid_cut = (row.get('current') is not None and row.get('new') is not None
                   and num(row.get('new')) < num(row.get('current')))
        if mismatch and not bid_cut:
            proof = listing_size.pause_proof(row, sizes, verification, dimension_pairs)
            if proof and row.get('relevance_hold') in (None, mismatch):
                row.pop('relevance_hold', None)
                row[listing_size.MARKER] = proof
                row['why'] = mismatch + ' Confirmed against the fresh live listing; positive keyword pause only.'
            else:
                row['relevance_hold'] = row['why'] = mismatch


def approved_phrase_reason(term, rel):
    return next((why for token, why in (rel.get('approved_phrase_exclusions') or {}).items()
                 if has(term, token)), None)


BRAND_DEMOTE = ('Rank', 'Defend', 'Hold', 'Test')   # the roles that fund or raise a search; Trim, Negate and Leave only cut
BRAND_BUILD = ('New exact campaign', 'Reuse exact campaign', 'New exact keyword', 'New SB video campaign', 'Business invest',
               'Budget and top of search', 'Budget step')


def demote_brand(records, brand, owner_kind=None):
    """Section 1c': every search record holding the brand (brand(t), plan()'s test on config scale_insights.blacklist_keep)
    whose role would fund or raise it (BRAND_DEMOTE) becomes Leave, cut only: the brand is organic only (Kim,
    2026-10-20). Every brand record is marked `brand`. Returns [{search, was, owner_kind}] for the summary's brand_guard."""
    out = []
    for t, r in records.items():
        word = brand(t)
        if not word:
            continue
        r['brand'] = word
        if r['role'] not in BRAND_DEMOTE:
            continue
        was = r['sub_role'] if r['role'] == 'Rank' else r['role']
        out.append(dict(search=t, was=was, **({'owner_kind': owner_kind} if owner_kind else {})))
        r.pop('season_rank', None)
        r.update(role='Leave', sub_role='Leave',
                 why=(f'brand search ("{word}"): organic only (Kim, 2026-10-20; config scale_insights.blacklist_keep), '
                      f'never invested in or raised. The ladder said {was}: {r["why"]}'))
    return out


def brand_sweep(changes, brand):
    """Section 4z: drop every row that would create, fund, whitelist or raise a brand search, whatever built it, and return
    them as [{type, keyword, why}] (summary.brand_guard.dropped_rows). The role pass (demote_brand) should leave none: a
    non-empty list means a section missed it, and the run says so. A blacklist rescue row that would free or whitelist the
    brand goes whole (blacklist_rescue.rescue keeps the brand since 2026-10-26; the rest of the rescue waits a run)."""
    dropped, keep = [], []
    for x in changes:
        text = str(x.get('keyword') or x.get('search') or '')
        lists = [str(e) for k in ('exact_remove', 'phrase_remove', 'whitelist_add') for e in (x.get(k) or [])]
        cur, new = x.get('current'), x.get('new')
        raise_ = isinstance(cur, (int, float)) and isinstance(new, (int, float)) and new > cur + 0.005
        if any(brand(e) for e in lists):
            why = 'would take the brand off the blacklist or whitelist it'
        elif text and brand(text) and (x.get('type') in BRAND_BUILD or str(x.get('type') or '').startswith('Scale Insights')):
            why = f"would build or fund a brand search ({x.get('type')})"
        elif text and brand(text) and raise_:
            why = f'would raise a brand search ({cur} -> {new})'
        else:
            keep.append(x)
            continue
        dropped.append(dict(type=x.get('type'), keyword=text, why=why))
    changes[:] = keep
    if dropped:
        print(f'brand guard: {len(dropped)} row(s) on the brand dropped (summary.brand_guard): '
              + '; '.join(f"{d['type']} {d['keyword']}" for d in dropped[:5]))
    return dropped


def make_irrelevant(asin, rel, sizes=()):
    # Product-specific exclusions explicitly approved by the owner outrank generic roots.
    # Ordinary inferred negatives keep the existing protection/converter review behavior.
    phrase = dict(rel.get('negate_phrase') or {})
    phrase.update(rel.get('extra_phrase') or {})
    exact = rel.get('negate_exact') or {}
    protect = rel.get('protect') or []
    never = [x.lower() for x in rel.get('never_target') or []]

    def irrelevant(t):
        mismatch = wrong_size(t, sizes)
        if mismatch:
            return mismatch
        approved = approved_phrase_reason(t, rel)
        if approved:
            return approved
        if any(has(t, p) for p in protect):
            return None
        if t in exact:
            return exact[t]
        for tok, why in phrase.items():
            if has(t, tok):
                return why
        if re.fullmatch(r'b0[a-z0-9]{8}', t) and t not in never:
            return 'competitor product page'
        return None
    return irrelevant


# ----------------------------------------------------------------------------- campaign families
def kind_fn(shared, campaigns):
    """Who a campaign's clicks come from: 'business' (Amazon-Business-exclusive), 'audience' (AMC / low-bid copies) or
    'consumer'. The live flag is the truth: a campaign whose siteRestrictions carry AMAZON_BUSINESS is business whatever
    it is called. The name marker catches the B2B campaigns whose record is not in hand (a search-term row only carries
    the name). Business wins over audience: a B2B campaign is a different shopper, not a cheaper copy of a consumer one."""
    b2b = shared.get('b2b_campaign_markers', ['B2B'])
    audience = shared.get('audience_campaign_markers', ['AMC', 'Low Bids', 'Low 0.'])
    flagged = {c.get('name') for c in campaigns or []
               if 'AMAZON_BUSINESS' in (c.get('siteRestrictions') or [])}

    def kind(name):
        name = name or ''
        if name in flagged or any(m in name for m in b2b):
            return 'business'
        if any(m in name for m in audience):
            return 'audience'
        return 'consumer'
    return kind


def family_fn(cfg, shared, kind=None):
    markers = shared.get('audience_campaign_markers', ['AMC', 'Low Bids', 'Low 0.'])
    harvest_suffix = shared['harvest']['campaign_suffix']

    def family(c):
        c = c or ''
        if kind and kind(c) == 'business':
            return 'Business'
        if harvest_suffix in c:
            return 'Harvest'
        if 'SKC' in c:
            return 'SKC'
        if any(m in c for m in markers):
            return 'Audience (low bids)'
        if 'SQP Potential' in c:
            return 'SQP test'
        if 'Search terms w sales' in c or 'STs (LI)' in c:
            return 'Search terms w sales'
        if 'Auto' in c:
            return 'Auto'
        return 'Other'
    return family


SKC_NAME = re.compile(r'Exact SKC - (.+?)(?: - TOS Rank)?\s*$')


def skc_keyword_from_name(name):
    m = SKC_NAME.search(name or '')
    return norm(m.group(1)) if m else None


# ----------------------------------------------------------------------------- evidence and funnel negatives (both kinds)
def volume_text(r):
    """A record's search volume in words: SQP's own count over its 12 weeks as always; a figure from the launch list or
    SoldScope says the window it was scaled to and where it came from (fix round 1, 2026-10-22)."""
    if (r.get('volume_basis') or 'SQP') == 'SQP':
        return f"{r['sqp_volume']:,} searches in 12 weeks"
    return f"{r['sqp_volume']:,} searches in {r['observed_days']} days ({r['volume_basis']}, scaled from a monthly figure)"


def evidence_text(r):
    """A row's evidence: what its search's record shows, '' without one. A consumer record: its index and where it was
    read, SQP purchases on our clicks, ad orders on clicks, the search's volume (volume_text), and for a rank term where its
    index and volume came from and its head-term flag (data-stage design 4.4). A business record (owner_kind 'business',
    business.records): its index on the B2B campaigns' own clicks, its B2B ad orders, the search's volume."""
    if not r:
        return ''
    business = r.get('owner_kind') == 'business'
    if business:
        bits = [f"index {r['index']:.2f} (B2B search-term report)" if r['index'] is not None else 'IDX unknown: no same-query market benchmark']
        if r['ad_clicks']:
            bits.append(f"B2B ads {r['ad_orders']} orders on {r['ad_clicks']} clicks")
    else:
        bits = [f"index {r['index']:.2f} ({'SQP' if r['index_basis'].startswith('SQP') else 'search-term report'})" if r['index'] is not None else 'IDX unknown: no same-query market benchmark']
        if r['sqp_our_clicks']:
            bits.append(f"SQP {r['sqp_our_purchases']} purchases on {r['sqp_our_clicks']} of our clicks")
        if r['ad_clicks']:
            bits.append(f"ads {r['ad_orders']} orders on {r['ad_clicks']} clicks")
    if r['sqp_volume']:
        bits.append(volume_text(r))
    if not business and r['role'] == 'Rank':   # where its index and volume came from, and a head-term flag (data-stage design 4.4)
        bits.append(f"basis: {r['index_basis']}; volume: {r.get('volume_basis') or 'none'}")
        if r.get('relevance_flag'):
            bits.append(f"flag: {r['relevance_flag']}")
    return '; '.join(bits)


def funnel_negatives(owned, st_rows, kind_name, kind, add, skipped, why, exact_marker, exact_why, variant_why,
                     owner_kind=None):
    """The funnel negatives of one shopper kind (rulebook section 3; inside the business kind, design 4c): every ad group
    of the kind that paid for one of its invest searches in 90 days, other than the search's owner campaigns, gets a
    negative exact for it, through add, highest 90-day spend first. Only the kind's own campaigns (kind(name) ==
    kind_name): the consumer owner never negates its search in a business campaign or an audience copy, and a business
    invest never in a consumer ad group. Two exceptions go to skipped instead: a close variant of the campaign's own exact
    keyword (variant_why(own)), and an ad group inside another exact campaign (exact_marker in its name, exact_why).

    owned: {invest search: the ids of the campaigns that own it}; a search not in it gets no negative. why: the rows'
    why. owner_kind ('business' for the business kind) goes on the rows and the skipped entries, after ad_group_id."""
    tag = dict(owner_kind=owner_kind) if owner_kind else {}
    hits = defaultdict(lambda: dict(clicks=0.0, orders=0.0, spend=0.0))
    names = {}
    for s in st_rows:
        t = norm(s.get('SearchTerm'))
        cn = s.get('CampaignName') or ''
        if t not in owned or (s.get('AdType') or 'SP') != 'SP' or kind(cn) != kind_name:
            continue
        if str(s.get('CampaignId')) in owned[t]:
            continue
        k = (t, str(s.get('CampaignId')), str(s.get('AdGroupId')))
        h = hits[k]
        h['clicks'] += num(s.get('Clicks')); h['orders'] += num(s.get('Orders')); h['spend'] += num(s.get('Spend'))
        names[k] = (cn, s.get('AdGroupName'))
    for (t, cid, ag), h in sorted(hits.items(), key=lambda kv: -kv[1]['spend']):
        cn, agn = names[(t, cid, ag)]
        own = skc_keyword_from_name(cn)
        if own and is_close_variant(t, own):
            skipped.append(dict(keyword=t, campaign=cn, ad_group_id=ag, **tag, why=variant_why(own)))
            continue
        if exact_marker in cn:
            skipped.append(dict(keyword=t, campaign=cn, ad_group_id=ag, **tag, why=exact_why))
            continue
        add(step=7, type='Negative exact', keyword=t, campaign=cn, ad_group=agn, clicks90=int(h['clicks']), orders90=int(h['orders']),
            spend90=round(h['spend'], 2), campaign_id=cid, ad_group_id=ag, **tag, why=why,
            how='MAP create sp_negative_keywords: negative exact, ad-group level')


# ----------------------------------------------------------------------------- core
def launch_state(cfg, sq, today_iso, shared):
    """The launch plan's view of the data stage (launch design section 5; data-stage design 4.7, 2026-10-22): {active, reason,
    sqp_queries, left_this_run}, read from stage.data_stage so the two never disagree about the 10-query line. `sq` is the dict
    load_inputs returns, or a list of SQP rows."""
    rows = list(sq.values()) if isinstance(sq, dict) else list(sq or [])
    st = stage.data_stage(cfg, rows, shared, today_iso)
    return dict(active=st['stage'] == 'launch', reason=st['reason'], sqp_queries=st['sqp_queries'],
                left_this_run=st['left_launch_this_run'])


def leak_summary(leak, changes, leak_pause, osh):
    """summary.organic.leak: the leak reading plus what this run paused for it. checked: the leak pass ran (the check
    tripped); acted: it paused at least one keyword (2026-11-04: B0SAMP0034 said acted with nothing paused, because no
    ordinary keyword had the clicks with no order); note says why a tripped check paused nothing."""
    paused = sorted({str(x.get('keyword')) for x in changes if x['type'] == 'Pause keyword'
                     and str(x.get('why') or '').startswith('Leak check')})
    sb_paused = sorted({str(x.get('keyword')) for x in changes if x['type'] == 'SB pause keyword'
                        and str(x.get('why') or '').startswith('Leak check')})
    out = dict(leak, paused=paused, sb_paused=sb_paused, checked=bool(leak_pause), acted=bool(paused or sb_paused))
    if leak_pause and not out['acted']:
        out['note'] = (f"tripped, but no ordinary keyword had {osh.get('leak_pause_clicks')}+ clicks and no order "
                       '(or each was still in its launch test): nothing to pause')
    return out


def build(asin, cfg, shared, run, mode, today_iso=None, now_utc=None, with_lanes=True, allow_volatile=False,
          partial_inventory=None):
    """The plan (see _build). The weekly leak check (organic_share.py, decision 175) needs the plan's rank campaigns: when
    the first plan's check trips, the product is planned again with its leaking ordinary keywords paused."""
    kw = dict(today_iso=today_iso, now_utc=now_utc, with_lanes=with_lanes, allow_volatile=allow_volatile,
              partial_inventory=partial_inventory)
    out = _build(asin, cfg, shared, run, mode, **kw)
    leak = ((out['summary'][0].get('organic') or {}).get('leak') or {})
    if leak.get('tripped'):
        out = _build(asin, cfg, shared, run, mode, leak_pause=True, **kw)
    # the coverage ledger (decision 155): every live campaign, keyword, target and ad group of the product, with who owns it
    # in this run; main() stops on an unowned one unless --accept-unowned
    if (shared.get('coverage') or {}).get('enabled'):
        out['coverage'] = coverage.ledger(out, cfg, shared, asin,
                                          lambda prefix: ([x for p in fs for x in load_items(p)] if (fs := files(run, prefix)) else None))
        out['summary'][0]['coverage'] = coverage.summary(out['coverage'])
    out.pop('_priced', None)
    return out


def _build(asin, cfg, shared, run, mode, today_iso=None, now_utc=None, with_lanes=True, allow_volatile=False,
           partial_inventory=None, leak_pause=False):
    th, bud, plc = shared['thresholds'], shared['budgets'], shared['placement']
    fb, dsc = shared['fallback'], shared['discovery']   # the search-term fallback's bars and the Discovery cap lift (data-stage design 4.4)
    PROFIT = float(cfg['profit_per_unit'])
    PRIOR = th['prior_clicks']
    # keyword bids priced on each search's own SQP conversion (Kim, 2026-10-29, decision 162): every click on the listing
    # for that search, ad and organic, shrunk toward the search's market by the 10-click prior; the ad report only for a
    # search SQP has no clicks for. An exact keyword bids its search's price; a broad, phrase or auto keyword bids the
    # click-weighted price of the searches it served. The roles (rulebook section 2) are unchanged. 'ad' is the rule before
    SQP_PRICE = (shared.get('pricing') or {}).get('search_conversion', 'ad') == 'sqp'
    # the campaigns this product's ads serve in (decision 156): one named without its ASIN joins the product's campaigns, a
    # multi-ASIN one is left out on purpose and listed (summary.campaign_scope, the coverage ledger)
    scope = load_ad_campaigns(run, asin) if (shared.get('inventory') or {}).get('ad_campaigns') else None
    sq, st_rows, kw_rows, sug, camps, recent, rank, sqp_data_through = load_inputs(run, asin, cfg, scope)
    # multi-product campaigns the product file lists (decision 155, inventory.shared_campaigns): their names don't carry this
    # ASIN, so they are read by id and join the product's campaigns; every row in them is priced at the lowest profit among
    # the AI products they advertise, cut only (section 4y). One shared with a non-AI product stays Scale Insights'
    shared_list = shared_campaign_list(cfg) if (shared.get('inventory') or {}).get('shared_campaigns') else {}
    shared_out = dict(listed=len(shared_list), read=0, no_profit=sorted(i for i, v in shared_list.items() if not v['profit_per_unit_min']))
    if shared_list:
        have = {str(c.get('campaignId')) for c in camps}
        extra_c = [c for c in load_shared_campaigns(run, set(shared_list)) if str(c.get('campaignId')) not in have]
        camps = camps + extra_c
        shared_out['read'] = len(extra_c)
        if not files(run, 'shared_campaigns'):
            shared_out['not_read'] = sorted(shared_list)
    review_date = today_iso or sgt_today()
    # a seasonal product (scripts/season.py, docs/seasonal-bidding.md): the weekly run plans its wake, rank build and
    # harvest; the last mile, off, review and asleep phases are dated steps, so nothing is planned in them
    season_now = season.state(cfg, dt.date.fromisoformat(review_date))
    if season_now and not season_now['plan']:
        sys.exit(f"{asin} is in the {season_now['phase']} phase ({season_now['text']}). Nothing planned: this phase's steps "
                 f"are dated open items (python scripts/season.py items).")
    # ---- the product's data stage (scripts/stage.py; data-stage design 4.1, 2026-10-22): launch, early or mature, from this
    #      run's SQP rows and the product file. Everything the stage changes reads stage_info: the window monthly volumes are
    #      scaled to, the search-term fallback and the flags (section 1), the summary, and the lanes (plan_lanes.assign). A
    #      product in stage launch has no SQP market to plan from: the launch list carries it (launch_list.py), and the launch
    #      plan's day-0 structure replaces this exit. A seasonal product is planned by its season block whatever the stage
    #      (rulebook section 8), so it never exits here
    sq_rows = list(sq.values())
    stage_info = stage.data_stage(cfg, sq_rows, shared, review_date)
    if stage_info['stage'] == 'launch' and not season_now:
        floor = shared['launch']['sqp_min_queries']
        sys.exit(f"{asin} is in the launch stage ({stage_info['sqp_queries']} SQP queries with impressions, under {floor}): build "
                 f"the launch list with scripts/launch_list.py; the planner takes the product over at {floor} queries")
    stage_name = stage_info['stage']
    window = stage_info['observed_days'] or stage.FULL_WINDOW_DAYS
    # the week-on-week guard (4.6): this run's newest SQP week against the product file's sqp_history. The text is computed at
    # every stage; the lanes hold promotions on it in stage early only (plan_lanes.assign). --allow-volatile lifts the hold;
    # the text is kept so the log can say it was lifted
    volatile_text = stage.volatile_week(cfg, sq_rows, sqp_data_through, shared)
    volatile_week = None if allow_volatile else volatile_text
    lane_inputs = load_lane_inputs(run)   # soldscope_volume.json feeds the volume ladder below; the lanes read the rest (section 6)
    soldscope = lane_inputs['soldscope']
    # DataDive Rank Radar volumes in the product file (the rank block), for the rank volume cap's cross-check (decision 182)
    datadive_sv = {norm(k.get('kw') or ''): k.get('sv') for k in ((cfg.get('rank') or {}).get('keywords') or [])
                   if isinstance(k, dict) and k.get('kw')}
    # a seasonal product's season curves (SoldScope weekly searches at the peak week, season.py), as monthly (x 52/12): the
    # rank cap binds a rank build too (Kim, 2026-11-04, decision 185: "Yes, cap seasonal too")
    season_peak = {norm(k): float(c['peak_searches']) * 52 / 12
                   for k, c in (((cfg.get('season') or {}).get('curves')) or {}).items()
                   if isinstance(c, dict) and isinstance(c.get('peak_searches'), (int, float)) and c['peak_searches'] > 0}
    launch_block = cfg.get('launch') or {}
    # what a head-term flag (4.4.4) is checked against: the launch list, the DataDive niche saved in the run, and the roots
    niche_terms = set()
    niche_path = os.path.join(run, 'niche_keywords.json')
    if os.path.exists(niche_path):
        niche = load_raw(niche_path)
        niche_terms = {norm(k['keyword']) for k in ((niche.get('keywords') if isinstance(niche, dict) else None) or [])
                       if isinstance(k, dict) and k.get('keyword')}
    roots = launch_block.get('roots') or (cfg.get('relevance') or {}).get('roots') or []
    # "unlisted" needs a list: a product with no launch list, no niche file and no roots (every product onboarded before the
    # design) has nothing to check a search against, so only its one-word searches are flagged (decided 2026-10-22)
    listable = bool(launch_block.get('searches') or niche_terms or roots)
    visibility_policy = shared.get('visibility') or {}
    visibility_inputs = load_visibility_inputs(run, asin) if visibility_policy.get('enabled') else {}
    raw_keyword_count = len(kw_rows)
    kw_rows = merge_keyword_inventory(kw_rows, visibility_inputs, asin, review_date, visibility_policy, camps)
    # every live keyword and target is priced, leaving none behind (config inventory; Kim, 2026-10-25, decision 135): the
    # live read adds the ones Scale Insights has no 90-day row for, and gives every row its live bid. One with no clicks of
    # its own is never raised on this run (no_data_raise false), except on a seasonal product, whose wake raises on purpose
    inv_cfg = shared.get('inventory') or {}
    live_inv = load_live_inventory(run)
    # a Scale Insights dayparting modifier still in Amazon's live bids (rule 203's weekend cut, -20% since 2026-10-31 (-40% before), stays until the weekday hours
    # open, Mon 06:00 PT): read from the keywords' stored bids, never the calendar, and every live bid read back to its base
    # before anything compares against it (daypart_base.py; Kim, 2026-10-26, decision 150)
    stored_kw = {str(r.get('KeywordId')): num(r.get('Bid')) for r in kw_rows if r.get('Bid') not in (None, '')}
    daypart_m, daypart_status = daypart_base.detect(
        [(stored_kw[str(k.get('keywordId'))], num(k.get('bid'))) for k in live_inv['keywords']
         if (k.get('state') or '').upper() == 'ENABLED' and str(k.get('keywordId')) in stored_kw and k.get('bid') not in (None, '')])
    daypart_out = dict(status=daypart_status, factor=daypart_m,
                       keywords=rebase_live(live_inv['keywords'], stored_kw, 'keywordId', daypart_m))
    # the factor is the one the bids show, so a weekend cut Kim changes in Scale Insights (-20%, -25%) is priced from the
    # full bid all the same; config.json write_window only needs to catch up (decision 152)
    configured = daypart_base.modifiers(shared)
    if daypart_status == 'modifier' and all(abs(daypart_m - m) > 0.02 for m in configured):
        daypart_out['config_differs'] = dict(
            configured=configured, note=f"the live bids show Scale Insights' modifier at x{daypart_m:g}, config.json "
                                        f"write_window.modifier says {configured}: the plan prices from the measured "
                                        f"x{daypart_m:g}; tell Kim so config.json can be updated")
    kw_rows, live_kw_counts = merge_live_keywords(kw_rows, live_inv['keywords'], camps, asin, paused=bool(inv_cfg.get('paused')))
    never_raise = inv_cfg.get('no_data_raise') is False and not season_now
    # the suggested mid (mid_bid.py; Kim, 2026-10-31, decision 177): validated and still-launching ordinary keywords bid
    # the suggested middle bid, not their breakeven. None when config.json mid_bid is off; a seasonal product in season
    # keeps its breakeven bids (docs/seasonal-bidding.md)
    mid_cfg = None if season_now else mid_bid.settings(shared)
    sb_mid_of = {}   # the SB keywords at the mid (the Sponsored Brands section fills it)
    # a keyword or target that is not a rank search bids this share of its breakeven click (Kim, 2026-10-26, decision 139:
    # "bid more conservatively for the rest of the keywords"): Hold, Defend, Test, Discovery and the audience cap. Rank
    # bids and Trim (70%) are unchanged. A seasonal product in season keeps its breakeven bids (docs/seasonal-bidding.md)
    nr = 1.0 if season_now else float(th.get('non_rank_bid_factor', 1.0))
    nr_base = nr   # the business keywords keep it: the organic share below is the consumer product's
    # the organic share, the top-10 rule and the leak check (organic_share.py; decision 143, reshaped 2026-10-31, decision
    # 175). The share is reported only: the organic-share brake that cut non-rank bids to 70% under 50% organic is gone
    # (Kim: "just let ordinary keywords stay at 100% of break-even"). Never a rank bid or a budget; never in season (its
    # breakeven bids are the season's plan)
    osh = organic_share.settings(shared)
    org_on = bool(osh['enabled']) and not season_now
    sales_daily = organic_share.load_sales(run, asin) if org_on else None
    share_now = organic_share.product_share(sales_daily, osh['share_days'])
    nr_words = 'breakeven' if nr == 1 else f'{nr:.0%} of breakeven'

    def pct_words(f):
        return 'breakeven' if f == 1 else f'{f:.0%} of breakeven'
    # a new seasonal listing has no SQP yet: its rank searches come from the season block, so it plans without
    if (not sq and not season_now) or not st_rows or not kw_rows:
        sys.exit(f'Missing inputs in {run}: sqp={len(sq)} search-term rows={len(st_rows)} keyword rows={len(kw_rows)}')
    # who each campaign's clicks come from (business / audience / consumer) and its family; SB campaigns are read up here
    # so the Business flag covers them too, and the video build below reuses the same read
    sb = load_sb(run, asin, tuple((shared.get('sb_video') or {}).get('multi_asin_markers') or ()))
    daypart_out['sb_keywords'] = rebase_live(sb['keywords'], {}, 'keywordId', daypart_m)
    kind = kind_fn(shared, camps + list(sb['campaigns'].values()))
    family = family_fn(cfg, shared, kind)
    sizes = product_sizes(asin, cfg)
    size_verification, size_verification_problem = listing_size.read_confirmation(
        run, cfg, own_sizes(asin, cfg), dimension_pairs, review_date, now_utc)
    irrelevant = make_irrelevant(asin, cfg.get('relevance') or {}, sizes)
    # the brand's searches are organic only (Kim, 2026-10-20: "YourBrand as the brand should be left to organic"; config
    # scale_insights.blacklist_keep): brand(t) is the brand word a search holds, "yourbrand birthday cards" as much as
    # "yourbrand" (blacklist_rescue.brand_search), or None
    brand_keep = (shared.get('scale_insights') or {}).get('blacklist_keep') or []

    def brand(t):
        return blacklist_rescue.brand_search(t, brand_keep)

    # ---- search-term aggregates (90 days, all ad types: what the product converts on). The B2B campaigns' rows are
    #      another shopper's (Amazon Business buyers convert about twice as well): they make ST_B, the business
    #      aggregates, and no longer count in ST, so neither kind's evidence is read as the other's (design 4a of
    #      docs/superpowers/specs/2026-10-21-b2b-lane-and-roles-design.md). Audience campaigns' rows stay in ST until
    #      phase 2 decides their place
    def aggregates():
        return defaultdict(lambda: dict(clicks=0.0, orders=0.0, spend=0.0, sales=0.0, imp=0.0, camps=set()))
    ST, ST_B = aggregates(), aggregates()
    for m in st_rows:
        s = (ST_B if kind(m.get('CampaignName')) == 'business' else ST)[norm(m.get('SearchTerm'))]
        s['clicks'] += num(m.get('Clicks')); s['orders'] += num(m.get('Orders')); s['spend'] += num(m.get('Spend'))
        s['sales'] += num(m.get('Sales')); s['imp'] += num(m.get('Impressions')); s['camps'].add(m.get('CampaignName'))
    ad_clicks = sum(s['clicks'] for s in ST.values())
    ad_orders = sum(s['orders'] for s in ST.values())
    ASIN_AD_CVR = ad_orders / ad_clicks if ad_clicks else th['test_default_market_cvr']
    mq = [q for q in sq.values() if q.get('AsinClicks') and q.get('TotalClicks') and q.get('TotalPurchase') is not None]
    ASIN_MKT_CVR = (sum(q['AsinClicks'] * q['TotalPurchase'] / q['TotalClicks'] for q in mq) /
                    sum(q['AsinClicks'] for q in mq)) if mq else ASIN_AD_CVR
    NO_ROWS = dict(clicks=0, orders=0, spend=0.0, sales=0.0, imp=0, camps=set())   # a search with no rows of a kind (read only)

    # a seasonal product prices each search on this season's SQP plus last season's same weeks (decision 172): the
    # conversion counts (our clicks and purchases, the market's clicks and purchases) are summed; volume, impressions and
    # organic stay this year's. An evergreen product plans on its newest SQP alone, however old (sqp_age_days)
    LS, ls_through = load_last_season(run, asin) if cfg.get('season') else ({}, None)
    CONV = ('AsinClicks', 'AsinPurchase', 'TotalClicks', 'TotalPurchase')

    def conv_row(t, q):
        """The SQP row a search's conversion is read from: q itself, or q with last season's counts added."""
        last = LS.get(t)
        if not last:
            return q
        out = dict(q or {})
        for k in CONV:
            if out.get(k) is not None or last.get(k) is not None:
                out[k] = (out.get(k) or 0) + (last.get(k) or 0)
        return out

    def market_of(q):
        """The search's market conversion, shrunk toward the product's market conversion: a search with 1 purchase on 1
        click is not a 100% market (animal bookmarks, 2026-10-17: Test bids went to the full $3.68 profit per order).
        None when the search has no SQP market."""
        MP = th.get('market_prior_clicks', 20)
        if q and q.get('TotalClicks') and q.get('TotalPurchase') is not None:
            return (q['TotalPurchase'] + MP * ASIN_MKT_CVR) / (q['TotalClicks'] + MP)
        return None

    def role_ladder(t, q, s, prior_cvr, irrelevant, owner_kind=None):
        """One search's record and its role on the ladder (rulebook section 1), from its SQP row q and its search-term
        aggregate s, its conversion estimate shrunk toward prior_cvr by the 10-click prior.

        Run once for consumers (s from ST, prior_cvr the search's shrunk market): SQP first, the search-term report second.
        Run again with owner_kind='business' for business buyers (s from ST_B, prior_cvr the B2B pool, design 4a): SQP
        counts every shopper, so a business record reads only the B2B campaigns' own clicks and orders, trusted at 10 of
        them or 3 orders, Invest at 3 orders. Its index is read against the search's market all the same (the shoppers
        differ, the search does not), and its volume, impression share and organic share are the search's product-level
        facts, the same on both records (organic = SQP purchases less both kinds' ad orders)."""
        business = owner_kind == 'business'
        qc = conv_row(t, q)   # this year's row, plus last season's counts for a seasonal product (decision 172)
        mk = market_of(qc)
        sq_c, sq_p = ((qc.get('AsinClicks') or 0), (qc.get('AsinPurchase') or 0)) if qc else (0, 0)
        own_p = (q.get('AsinPurchase') or 0) if q else 0   # this year's purchases: organic is this year's
        if business:
            enough = s['clicks'] >= th['trusted_min_clicks'] or s['orders'] >= th['trusted_min_ad_orders']
            basis, c, p = ('Search terms (business)' if enough else 'Search terms (business, thin)'), s['clicks'], s['orders']
        elif sq_c >= th['trusted_min_clicks']:
            basis, c, p = 'SQP', sq_c, sq_p
        elif s['clicks'] >= th['trusted_min_clicks'] or s['orders'] >= th['trusted_min_ad_orders']:
            basis, c, p = 'Search terms', s['clicks'], s['orders']
        elif sq_c > 0:
            basis, c, p = 'SQP (thin)', sq_c, sq_p
        elif s['clicks'] > 0:
            basis, c, p = 'Search terms (thin)', s['clicks'], s['orders']
        else:
            basis, c, p = 'No clicks yet', 0, 0
        cvr_est = (p + PRIOR * prior_cvr) / (c + PRIOR)
        idx = cvr_est / mk if mk and mk > 0 else None
        # the price (decision 162): a consumer search with any SQP clicks of ours is priced on SQP, however few (shrunk toward
        # its market); with none, on the record the role reads. The role and index above are unchanged
        if SQP_PRICE and not business and sq_c > 0:
            price_basis, cvr_price = ('SQP' if sq_c >= th['trusted_min_clicks'] else 'SQP (thin)'), (sq_p + PRIOR * prior_cvr) / (sq_c + PRIOR)
            if t in LS:
                price_basis += ' + last season'
        else:
            price_basis, cvr_price = basis, cvr_est
        trusted = basis in ('SQP', 'Search terms', 'Search terms (business)') and idx is not None
        # volume from the next source down (data-stage design 4.4.3): SQP's own count, else the launch list's or SoldScope's
        # monthly figure scaled to the product's SQP window, else 0; vol_basis says which
        vol, vol_basis = stage.volume_of(t, q, launch_block, soldscope, window)
        # the rank volume cap (decision 182, Kim 2026-11-04): a consumer search with more than
        # thresholds.rank_max_monthly_searches a month is never a rank search (no Invest, no Prove first): over two weeks on
        # 66 products, rank moved on searches of about 500-2,000 a month (DataDive) and not above. It bids as Defend, at its
        # breakeven, and a logged one steps down (section 3b's slip loop). 3,000 a month since decision 189 (2026-11-05)
        # a product whose listing is ready for bigger searches (more reviews and variations; Kim, 2026-11-04: "when it is
        # 'time', we try going for the bigger search volumes, like 3000 to 5000 and subsequently 5000 to 10000 and >10000")
        # carries its own cap in its product file (rank_max_monthly_searches); a person raises it
        cap = cfg['rank_max_monthly_searches'] if 'rank_max_monthly_searches' in cfg else th.get('rank_max_monthly_searches')
        monthly = evidence.monthly_searches(vol, window if vol_basis in ('launch list', 'SoldScope') else
                                            ((q.get('QueryObservedDayCount') or stage.FULL_WINDOW_DAYS) if q else stage.FULL_WINDOW_DAYS))
        # cross-checked (Kim, 2026-11-04): the highest of SQP, DataDive and SoldScope, each at its own number (decision 189
        # dropped the 0.8 DataDive conversion), so a search one source undercounts is still capped
        monthly, cap_sources = stage.cap_volume(monthly, datadive_sv.get(norm(t)), soldscope.get(norm(t)),
                                                season_monthly=season_peak.get(norm(t)))
        # the strong-index band (decision 189, Kim, 2026-11-05): a search we convert on at least rank_cap_strong_index
        # (1.3) times the market, on trusted clicks, may be a rank search up to rank_cap_strong_max (4,000) a month, or the
        # product's own cap when that is higher
        cap = stage.rank_cap_for(cap, idx if trusted else None, th.get('rank_cap_strong_index'), th.get('rank_cap_strong_max'))
        over_cap = bool(not business and cap is not None and monthly is not None and monthly > float(cap))
        # the search-term fallback (4.4.2): a consumer search with no same-query market, in stage early, whose ads convert well
        # against the product's market conversion may reach Prove first, and nothing more (never Invest, Hold, Trim or a
        # raise): its index stays None, the value lives in fallback_index, and only the Rank branch below reads it
        fb_idx = (stage.fallback_index(s['clicks'], s['orders'], ASIN_MKT_CVR, PRIOR)
                  if not business and mk is None and s['clicks'] > 0 else None)
        fallback = (fb_idx is not None and stage_name == 'early' and s['clicks'] >= fb['min_clicks'] and not over_cap
                    and s['orders'] >= fb['prove_orders'] and at_least(fb_idx, fb['prove_index']) and vol >= th['invest_min_volume'])
        # organic = SQP purchases less every ad order of the search, consumer and business: a B2B order is an order of the
        # same ASIN and sits in SQP's purchases (spec 9b, ruling 5). The same count as before the split, so
        # an invest log's organic_then (the stop-loss baseline, design 4f) still compares like with like
        ad_orders_all = (ST.get(t) or NO_ROWS)['orders'] + (ST_B.get(t) or NO_ROWS)['orders']
        organic = max(0, own_p - ad_orders_all) if q else None
        org_share = (organic / own_p) if (q and own_p) else None
        imp_share = (q['AsinImpressions'] / q['TotalImpressions']) if q and q.get('TotalImpressions') else None
        clicks_word = 'B2B clicks' if business else 'clicks'
        why_irr = irrelevant(t)
        if why_irr:
            role, why = 'Negate', why_irr
        elif (trusted and at_least(idx, th['index_invest']) and vol >= th['invest_min_volume'] and not over_cap and
              not (imp_share is not None and imp_share >= th['defend_impression_share'] and
                   org_share is not None and org_share >= th['defend_organic_share'])):
            role, why = 'Rank', f'beats the market ({idx:.2f}) on {int(c)} of our {clicks_word}'
        elif trusted and at_least(idx, th['index_invest']) and over_cap:
            role, why = 'Defend', (f'beats the market ({idx:.2f}) but has about {monthly:,.0f} searches a month, over the '
                                   f'{float(cap):,.0f} rank cap ({", ".join(cap_sources)}; decision 182): bid at breakeven, no rank investment')
        elif trusted and at_least(idx, th['index_invest']):
            role, why = 'Defend', f'beats the market ({idx:.2f}) but is small or already mostly organic'
        elif trusted and at_least(idx, th['index_hold']):
            role, why = 'Hold', f'converts at the market ({idx:.2f})'
        elif trusted and c >= th['trim_min_clicks']:
            role, why = 'Trim', f'trails the market ({idx:.2f}) on {int(c)} {clicks_word}'
        elif fallback:
            role, why = 'Rank', (f"no SQP row yet; its ads convert {fb_idx:.2f}x the product's market ({int(s['orders'])} orders on "
                                 f"{int(s['clicks'])} clicks, {PRIOR:g}-click prior): Prove first on the search-term fallback")
        elif vol >= th['invest_min_volume'] or s['orders'] >= 1:
            role, why = 'Test', ('same-query market benchmark unavailable; IDX unknown; validate using own economics'
                                 if idx is None else f'not enough of our {clicks_word} to judge yet ({int(c)})')
        else:
            role, why = 'Leave', 'small search, no data'
        validated_prove = False
        if role == 'Test' and not business and mid_cfg and idx is not None and max(own_p, s['orders']) >= mid_cfg['validated_orders']:
            # decision 177: a Test search is validated at 2+ orders (the higher of its SQP purchases and its ad orders, as the
            # ladder counts them) before it has the clicks to be trusted: index auto.prove_index (1.1 since decision 178) or more
            # goes to Prove first (on enough volume), under 0.8 to Trim; in between stays a Test keyword at the mid (mid_bid.state)
            got = int(max(own_p, s['orders']))
            if at_least(idx, mid_cfg['index_to']) and vol >= th['invest_min_volume'] and not over_cap:
                role, validated_prove = 'Rank', True
                why = f'validated: {got} orders at index {idx:.2f} on {int(c)} of our {clicks_word}: Prove first (decision 177)'
            elif idx < mid_cfg['index_from']:
                role, why = 'Trim', f'validated: {got} orders but trails the market ({idx:.2f}) (decision 177)'
        thin = (s['orders'] < th['invest_min_purchases'] if business else
                sq_p < th['invest_min_purchases'] and s['orders'] < th['invest_min_purchases'])
        # observed_days is the window the volume was counted over, so evidence.monthly_searches inverts the scaling: the
        # product's window for a monthly figure scaled to it (an SQP row with no volume of its own included, R35 2026-10-22),
        # else the SQP row's own count, else the full 84 days; sqp_observed_days is the SQP row's own count, None without a
        # row (the lanes' two-week check reads it)
        sqp_days = (q.get('QueryObservedDayCount') or stage.FULL_WINDOW_DAYS) if q else None
        record = dict(term=t, role=role, sub_role=('Prove first' if (thin or fallback or validated_prove) else 'Invest') if role == 'Rank' else role, why=why,
                      sqp_volume=vol, volume_basis=vol_basis, monthly_searches=r2(monthly) if monthly is not None else None,
                      over_rank_cap=over_cap, rank_cap=(float(cap) if cap is not None else None), rank_cap_sources=cap_sources,
                      observed_days=window if vol_basis in ('launch list', 'SoldScope') else (sqp_days if q else stage.FULL_WINDOW_DAYS),
                      sqp_observed_days=sqp_days, stage=stage_name,
                      market_cvr=mk, sqp_our_clicks=(q.get('AsinClicks') or 0) if q else 0, sqp_our_purchases=own_p,
                      last_season_clicks=(LS[t].get('AsinClicks') or 0) if t in LS else None,
                      last_season_purchases=(LS[t].get('AsinPurchase') or 0) if t in LS else None,
                      sqp_total_clicks=(q.get('TotalClicks') or 0) if q else 0,
                      ad_clicks=int(s['clicks']), ad_orders=int(s['orders']), ad_spend=round(s['spend'], 2), ad_sales=round(s['sales'], 2),
                      ad_cpc=(s['spend'] / s['clicks']) if s['clicks'] else None,
                      index_basis='Search terms vs product market' if fallback else basis, index=r2(idx),
                      index_status=('same_query_smoothed' if idx is not None else
                                    'product_market_fallback' if fallback else 'unknown_market_benchmark'),
                      fallback_index=r2(fb_idx) if fallback else None, relevance_flag=None,
                      cvr_est=round(cvr_est, 4), cvr_price=round(cvr_price, 4), price_basis=price_basis,
                      organic_purchases=organic, organic_share=org_share, impression_share=imp_share,
                      be_cpc=round(PROFIT * cvr_price, 2), n_campaigns=len(s['camps']))
        if business:
            record['owner_kind'] = 'business'
        return record

    # ---- 1. role of every search (SQP first, search-term report second, shrunk toward the market)
    terms = {}
    season_rank = set((season_now or {}).get('rank_searches') or [])
    for t in set(sq) | set(ST) | season_rank:
        if not t:
            continue
        q = sq.get(t)
        terms[t] = role_ladder(t, q, ST.get(t, NO_ROWS), market_of(conv_row(t, q)) or ASIN_MKT_CVR, irrelevant)
    # the head-term flags (data-stage design 4.4.4, 2026-10-22): a one-word search, or one in neither the launch list nor the
    # niche nor matched by a root, is a person's call when it is promoted (lanes.classify); other rows carry it as information
    for t, r in terms.items():
        flag = stage.relevance_flag(t, launch_block, niche_terms, roots)
        r['relevance_flag'] = None if flag == 'unlisted' and not listable else flag
    # ---- 1a. a logged Prove first that SQP still shows no same-query market for stays a rank term (data-stage design 4.4.2,
    #          2026-10-22): the search-term fallback promoted it, so there is no row to re-judge it by, and its exit is the
    #          stop-loss review (rulebook section 4), never a Test re-price of its exact campaign. It is deferred like any
    #          retained investment (kept at its live bid, out of the re-rank). The moment SQP shows the query, the ladder decides
    for t, log in (cfg.get('invest_log') or {}).items():
        r = terms.get(norm(t))
        if (r and isinstance(log, dict) and log.get('since') and log.get('role') == 'Prove first' and r['index'] is None
                and r['role'] in ('Test', 'Leave')):
            r.update(role='Rank', sub_role='Prove first', retained_log=True,
                     why=(f"in the invest log as Prove first since {log['since']} and SQP shows no same-query market yet: kept a "
                          f"rank term until its stop-loss review, never re-cut as a Test; {r['why']}"))
    # ---- 1b. a seasonal product: in a rank build the season block's rank searches are its only invest searches (picked
    #          from SoldScope volume: a new seasonal listing has no SQP, and Rank needs 150+ SQP searches); in wake and
    #          harvest nothing is invested in. A search that would be Rank otherwise bids as Defend, at its breakeven.
    if season_now:
        for t, r in terms.items():
            if r['role'] == 'Negate':
                continue
            if t in season_rank and r.get('over_rank_cap') and not season_now['harvest']:
                # over the rank cap (decision 185, Kim 2026-11-04: "Yes, cap seasonal too"): a season search too big
                # for rank investment bids as Defend; its exact keyword takes the suggested low, never under breakeven
                r.update(role='Defend', sub_role='Defend', season_defend=True,
                         why=(f"season rank search over the rank cap ({', '.join(r.get('rank_cap_sources') or [])}; "
                              f"decision 185): not invested in, the suggested low on its exact keyword; {r['why']}"))
            elif t in season_rank:
                r.update(role='Rank', sub_role='Invest', season_rank=True,
                         why=f"season rank search ({season_now['name']}, rank build to {season_now['rank_build_end']}): "
                             f"picked from SoldScope search volume; {r['why']}")
            elif r['role'] == 'Rank':
                r.update(role='Defend', sub_role='Defend', season_defend=True,
                         why=('harvest: no invest searches, its breakeven bid' if season_now['harvest'] else
                              "rank build: not one of the season's rank searches, its breakeven bid") + f"; {r['why']}")
    # ---- 1c'. a brand search is never invested in, held at breakeven or tested (brand(), above): whatever the ladder, a
    #          retained Prove first or the season said, it bids as Leave, cut only (section 2, the SB pricing and the brand
    #          sweep before section 5). The 2026-10-26 rollout run made "yourbrand birthday cards" (index 1.21) an Invest
    #          search on B0SAMP0014 and launched it, live 14 minutes before it was reversed by hand
    brand_searches = demote_brand(terms, brand)
    rank_terms = [t for t, r in terms.items() if r['role'] == 'Rank']
    # the top-10 rule (decision 143; 75% since decision 175): a non-rank keyword on a search the product already ranks for
    # organically bids 75% of breakeven, so the ads don't buy what the product gets for free; rank searches keep investing. Rank Radar's 14-day median, else SQP's organic share
    radar_early = load_radar(run) if org_on else {}
    top10 = organic_share.top10_searches(terms, radar_early, osh, th['defend_organic_share']) if org_on else {}

    def nr_for(t):
        return min(nr, float(osh['top10_factor'])) if t in top10 else nr

    # ---- 1c. the business search records (design 4a): the same ladder, run on the B2B campaigns' own search-term rows
    #          for every search they have rows for or a business keyword holds. The prior is the B2B pool: the business
    #          keyword rows' 90-day orders and clicks, shrunk by the 10-click prior toward the account's B2B conversion, a
    #          dated config number refreshed monthly (Kim, 2026-10-21: "lean on the b2b conversion for b2b campaigns";
    #          references/data-pull.md, "Monthly"). Without it, the product's consumer ad conversion, as phase 1 did, and
    #          the summary says which
    biz_cfg = shared.get('business') or {}
    if biz_cfg.get('pool_prior_cvr'):
        pool_prior = float(biz_cfg['pool_prior_cvr'])
        pool_prior_out = dict(cvr=round(pool_prior, 4), as_of=biz_cfg.get('pool_prior_as_of'), source='config')
    else:
        pool_prior = ASIN_AD_CVR
        pool_prior_out = dict(cvr=round(pool_prior, 4), as_of=review_date, source='product ad conversion')
    b2b_rows = business.keyword_rows(kw_rows, family)   # the B2B campaigns' keyword rows: the pool's, records' and owners'
    B2B_CVR = business.pool(b2b_rows, pool_prior, PRIOR, num)
    # the business search records (business.records). ctx is the working state the business sections of business.py read
    # and set (each function's docstring says which): filled here with the run's inputs and what the records need, each
    # later section's names added just before its call
    ctx = types.SimpleNamespace(asin=asin, cfg=cfg, shared=shared, th=th, bud=bud, plc=plc, PROFIT=PROFIT,
                                sq=sq, st_rows=st_rows, kw_rows=kw_rows, b2b_rows=b2b_rows, camps=camps, kind=kind,
                                irrelevant=irrelevant, ST_B=ST_B, NO_ROWS=NO_ROWS, role_ladder=role_ladder,
                                season_now=season_now, biz_cfg=biz_cfg, B2B_CVR=B2B_CVR, pool_prior_out=pool_prior_out,
                                num=num, write_json=write_json, load_suggested=load_suggested,
                                evidence_text=evidence_text, funnel_negatives=funnel_negatives, nr=nr_base)
    business_terms = business.records(ctx)
    brand_searches += demote_brand(business_terms, brand, owner_kind='business')
    business_rank_terms = [t for t, r in business_terms.items() if r['role'] == 'Rank']

    # the business owner of each business invest search, and the B2B exact campaign and ad group a new business exact
    # keyword goes into (business.owners_and_homes; design 4c)
    ctx.business_terms = business_terms
    ctx.owners = business.owners_and_homes(ctx)
    business_owner = ctx.owners.owner_by_search

    # Amazon's suggested bids are required for every invest search before bidding it
    contextual = {}
    for item in kw_rows:
        inventory = item.get('visibility_inventory') or {}
        recommendation, reason = visibility.match_recommendation(inventory, visibility_inputs, review_date, visibility_policy)
        if recommendation:
            contextual[str(item.get('KeywordId'))] = recommendation
    rank_suggestions = dict(sug)
    for item in kw_rows:
        recommendation = contextual.get(str(item.get('KeywordId')))
        if recommendation and item.get('MatchType', '').lower() == 'exact':
            rank_suggestions.setdefault(norm(item['Keyword']), [recommendation[key] for key in ('low', 'median', 'high')])
    # a search over the rank volume cap (decision 182) bids its suggested low, so its exact suggestion is read too
    # (any role but Negate: a validated Test or Hold search over the cap bids its low too, decision 183; B0SAMP0035's
    # "calendar for kids", a Test at index 2.11, was stepped down to breakeven under its $0.73 low on 2026-11-04)
    cap_terms = sorted(t for t, r in terms.items() if r.get('over_rank_cap') and r.get('role') != 'Negate')
    missing = [t for t in rank_terms if t not in rank_suggestions] + [t for t in cap_terms if t not in rank_suggestions
                                                                     and t not in rank_terms]
    # the suggested mid's keywords (mid_bid.py, decision 177): each live ordinary keyword's state, the owning copy of each
    # duplicate, and the Amazon mids still to read: an exact search joins the invest searches in need_suggested_bids.json,
    # a broad or phrase keyword its keywords list (suggested_bids_match.json)
    mid_match = mid_bid.load_match(run) if mid_cfg else {}

    def mid_lane(m):
        """Keyword row m's state under decision 177 (mid_bid.state), or None: business, audience, brand, wrong-size,
        paused and not-live keywords keep their own rules."""
        if not mid_cfg or m.get('not_live') or m.get('inventory_hold'):
            return None
        kw, mt = norm(m['Keyword']), (m.get('MatchType') or '').lower()
        if family(m.get('CampaignName') or '') in ('Business', 'Audience (low bids)') or brand(kw) or wrong_size(kw, sizes):
            return None
        if mt not in mid_cfg['match_types']:
            return None   # decision 183: broad and phrase keep their role's price (breakeven)
        t = terms.get(kw)
        clk, od = num(m.get('Clicks')), num(m.get('Orders'))
        if mt == 'exact' and t and t.get('over_rank_cap'):
            return None   # decision 183: an exact keyword on a search over the rank cap bids the suggested low, not the mid
        if mt == 'exact':
            role = t['role'] if t else 'Test'
            ladder = max(od, t.get('sqp_our_purchases') or 0, t.get('ad_orders') or 0) if t else od
            index = t.get('index') if t else None
        elif t and t['role'] == 'Negate':
            return None
        else:
            # a broad or phrase keyword: its own orders, and its own conversion (the 10-click prior toward the product's ad
            # conversion) against the product's ad conversion, as the Discovery cap lift reads it
            role, ladder = 'Discovery', od
            index = ((od + PRIOR * ASIN_AD_CVR) / (clk + PRIOR)) / ASIN_AD_CVR if ASIN_AD_CVR else None
        return mid_bid.state(role, clk, od, ladder, index, mid_cfg, ASIN_AD_CVR)

    mid_state = {str(m.get('KeywordId')): mid_lane(m) for m in kw_rows} if mid_cfg else {}
    mid_owner = mid_bid.owners([(str(m.get('KeywordId')), norm(m['Keyword']), (m.get('MatchType') or '').lower(),
                                 num(m.get('Clicks')), num(m.get('Orders')))
                                for m in kw_rows if mid_state.get(str(m.get('KeywordId'))) in mid_bid.MID_STATES])
    mid_need_keywords = []
    for m in kw_rows:
        kid, kw, mt = str(m.get('KeywordId')), norm(m['Keyword']), (m.get('MatchType') or '').lower()
        if mid_owner.get((kw, mt)) != kid or kid in contextual:
            continue
        if mt == 'exact' and kw not in sug and kw not in missing:
            missing.append(kw)
        elif mt != 'exact' and kw not in (mid_match.get(mt) or {}):
            mid_need_keywords.append(dict(text=kw, match_type=mt.upper()))
    # once Amazon was tried (bid_sources_tried.json), a search it gave no suggestion for is priced by the fallback chain
    # instead of stopping the run: SoldScope, then an estimate, then the no-suggestion bid (bid_fallback; decision 106)
    bids_tried = bid_fallback.tried(run)
    fallback_values, fallback_sources = {}, {}
    missing_rank = [t for t in missing if t in rank_terms or t in cap_terms]
    if (missing or mid_need_keywords) and bids_tried is not None:
        if missing_rank:
            fallback_values, fallback_sources = bid_fallback.fill(missing_rank, bid_fallback.load_soldscope(run, load_suggested),
                                                                  terms, rank_suggestions, shared)
            rank_suggestions.update(fallback_values)
        missing, mid_need_keywords = [], []
    if missing or mid_need_keywords:
        write_json(os.path.join(run, 'need_suggested_bids.json'),
                   dict(asin=asin, searches=sorted(missing), keywords=mid_need_keywords,
                        how='MAP get_amazon_ads_ad_group_bid_recs on any enabled ad group of this ASIN, keywords [{text, match_type: EXACT}], '
                            'save {"search": [low, median, high]} into suggested_bids.json, then rerun. For a search Amazon has '
                            "none for, or still rate-limits after one retry about 5 minutes later: save SoldScope's estimate for "
                            'the exact query in soldscope_bids.json if it has one, write what you tried in bid_sources_tried.json, '
                            'and rerun; the planner prices the rest itself (references/data-pull.md). keywords: empty since '
                            'decision 183 (the mid is for exact keywords only); only if config mid_bid.match_types lists '
                            'broad or phrase again: the same call with their own match_type, saved as {"broad": {"text": '
                            '[low, median, high]}, "phrase": {...}} in suggested_bids_match.json.'), indent=1)
        print(f'{len(missing) + len(mid_need_keywords)} searches and keywords need Amazon suggested bids first: '
              'see need_suggested_bids.json')
    # the business invest searches' suggestions, read in their own B2B ad group (business.bid_pull, design 4h): their need
    # file is written after the consumer one, and the run exits 2 when either file was (until Amazon was tried)
    ctx.business_rank_terms = business_rank_terms
    ctx.bids_tried = bids_tried
    business.bid_pull(ctx, run)
    if missing or mid_need_keywords:
        sys.exit(2)

    def cap_low(kw):
        """The suggested low a search over the rank cap bids (decision 182): Amazon's, else the fallback's (SoldScope, an
        estimate) once Amazon was tried; None without one (the search keeps its breakeven)."""
        v = rank_suggestions.get(kw) if kw in cap_terms else None
        return v[0] if v and v[0] and v[0] > 0 else None

    def cap_low_src(kw):
        kind = (fallback_sources.get(kw) or ('amazon', ''))[0]
        return {'soldscope': "SoldScope's low", 'estimate': 'estimated low'}.get(kind, "Amazon's low")

    # the suggested mid of each owning copy (mid_bid.pick): Amazon, then SoldScope once Amazon was tried, then an estimate
    mid_soldscope = bid_fallback.load_soldscope(run, load_suggested) if mid_cfg else {}
    mid_peers = [v[1] for v in sug.values() if v and v[1]] + [r['median'] for r in contextual.values() if r.get('median')]

    def mid_value(kid, kw, mt, own_cpc, own_clicks, tried=None):
        """(mid, source, words) for a keyword (mid_bid.pick). A Sponsored Brands keyword (kid None) reads its search's
        Sponsored Products figures and passes tried=True: Amazon has no Sponsored Brands suggestion to wait for."""
        rec = contextual.get(str(kid)) if kid is not None else None
        amazon = ((rec['low'], rec['median'], rec['high']) if rec else
                  sug.get(kw) if mt == 'exact' else (mid_match.get(mt) or {}).get(kw))
        return mid_bid.pick(amazon, mid_soldscope.get(kw), bids_tried is not None if tried is None else tried, own_cpc,
                            own_clicks, mid_peers, mid_cfg)

    # ---- 2. what every live keyword should bid
    big = {norm(k): v for k, v in (cfg.get('budget_overrides') or {}).items()}

    def invest_budget(t, sub):
        return big.get(t, bud['invest_per_day'] if sub == 'Invest' else bud['prove_per_day'])

    def invest_bid_unrounded(med, hi, be):
        """An invest search's Sponsored Products bid before rounding (rulebook section 1), for both kinds: Amazon's
        suggested median, or breakeven if higher, never above the suggested high; with no suggestion, 1.5x breakeven.
        A fallback estimate has no high (bid_fallback, decision 106): its bid is the estimate, or breakeven if higher.
        invest_bid_for and the New exact campaign and Reuse exact campaign rows round it; the Sponsored Brands invest_bid
        scales it by sb_cvr_ratio first, then rounds."""
        if not med:
            return be * th['no_suggestion_multiplier']
        return min(max(med, be), hi) if hi else max(med, be)

    def invest_bid_for(lo, med, hi, be, fallback=None):
        """An invest keyword's bid (invest_bid_unrounded, rounded) and where it came from; fallback, a search's
        (kind, note) from bid_fallback when Amazon gave it no suggestion."""
        bid = round(invest_bid_unrounded(med, hi, be), 2)
        if fallback:
            return bid, 'no Amazon suggestion; ' + fallback[1]
        return bid, f"Amazon's suggested ${lo:.2f}-${hi:.2f}" if med else 'no Amazon suggestion; 1.5x breakeven'

    def test_bid(market_price, be, f=None):
        """A Test bid (rulebook section 2): its market's breakeven click, lifted to the floor only as far as its own
        breakeven (Kim, 2026-10-25, decision 135: the $0.35 floor was twice a $1.79-a-unit product's breakeven click),
        times the non-rank share (decision 139)."""
        return round(max(market_price, min(th['test_floor_bid'], be)) * (nr if f is None else f), 2)

    BUSINESS_COPY_PAUSE = 'Pause here: the business owner holds this search'
    copy_price = {}   # keyword id of a business copy -> its phase 1 price, for when its owner doesn't invest

    # the consumer owner of a search, by the "SKC" in its campaign's name. A B2B campaign named like an SKC is the business
    # owner (rulebook 9.1): it never stands in for the consumer SKC, so the promotion still goes out and the consumer
    # exacts move into it rather than being paused as that campaign's copy
    # the Hold uplift test (config.json hold_uplift; decision 108): None when it is off
    hold_up = shared.get('hold_uplift') or {}
    hold_up = hold_up if hold_up.get('enabled') else None
    skc_terms = {norm(m['Keyword']) for m in kw_rows if 'SKC' in (m.get('CampaignName') or '')
                 and (m.get('MatchType') or '').lower() == 'exact' and family(m.get('CampaignName')) != 'Business'}
    # idle exact SKC campaigns (no spend, so missing from the keyword report) still own their search: consumer ones only
    # (a business campaign is the other kind's owner, and an AMC copy is never an owner, rulebook 9.1)
    live_skc = {}
    for c in camps:
        if (c.get('state') or '').upper() == 'ARCHIVED' or kind(c.get('name')) != 'consumer':
            continue
        k = skc_keyword_from_name(c.get('name'))
        if k:
            live_skc.setdefault(k, c)
    plan = []
    retained_rank_terms = {norm(term) for term in (cfg.get('invest_log') or {})}
    retained_rank_terms.update(norm(row.get('keyword')) for row in (cfg.get('proposed_rank_experiments') or {}).get('rows', []))
    # an Amazon Business campaign is its own shopper, not a consumer duplicate (design 4d): its keywords are priced on the
    # business evidence (section 1c: the search's business record, or the B2B pool), never on the consumer search's role
    # the searches each keyword served (90 days, consumer rows of the search-term report, SP and SB), for decision 162: a broad,
    # phrase or auto keyword bids the click-weighted price of the searches it actually served, not the product's average
    served = defaultdict(lambda: defaultdict(float))
    for m in st_rows:
        if kind(m.get('CampaignName')) != 'business' and m.get('KeywordId') and num(m.get('Clicks')) > 0:
            served[str(m['KeywordId'])][norm(m.get('SearchTerm'))] += num(m.get('Clicks'))

    def served_price(kid):
        """The click-weighted price (cvr_price) of the searches keyword kid served, and its clicks and searches; None when
        it served none with a record (decision 162)."""
        got = [(c, terms[s]['cvr_price']) for s, c in (served.get(str(kid)) or {}).items() if s in terms]
        n = sum(c for c, _ in got)
        # trusted only on thresholds.trusted_min_clicks (10) served clicks: with no +25% step (decision 165), one click on a
        # thin search (2 purchases on 2 SQP clicks, Oct 29) would take a broad keyword from $0.35 to $1.51 in one run
        if not SQP_PRICE or n < th['trusted_min_clicks']:
            return None
        return sum(c * p for c, p in got) / n, n, len(got)

    for m in kw_rows:
        kw, mt, camp = norm(m['Keyword']), (m.get('MatchType') or '').lower(), m.get('CampaignName') or ''
        fam = family(camp)
        clk, od, sp, sl = num(m.get('Clicks')), num(m.get('Orders')), num(m.get('Spend')), num(m.get('Sales'))
        bid = num(m.get('Bid')) if m.get('Bid') not in (None, '') else None
        t = terms.get(kw)
        if mt == 'exact' and t:
            role, prior = t['role'], t['cvr_est']
        elif mt == 'exact':
            role, prior = 'Test', ASIN_AD_CVR
        else:
            role, prior = 'Discovery', ASIN_AD_CVR
            if t and t['role'] == 'Negate':
                role = 'Negate'
        if wrong_size(kw, sizes):
            role = 'Negate'  # includes enabled keywords with no SQP or search-term record
        idx_b = None   # a business keyword's own index (below); bound on every row so the name never leaks from the last
        bt = None
        if fam == 'Business':
            # the business record's role (design 4b): an exact keyword takes its search's business role (every business
            # keyword's search has a record, section 1c), a phrase or broad keyword is Discovery, and an irrelevant search is
            # negated first, as in phase 1. Its own clicks and orders are shrunk toward its search's business conversion (an
            # exact row, as a consumer exact leans on the consumer record's) or the B2B pool (a phrase or broad row, which
            # catches many searches); its own index is read against the search's market only when the search has one
            bt = business_terms.get(kw) if mt == 'exact' else None
            if irrelevant(kw):
                role, prior = 'Negate', (bt['cvr_est'] if bt else B2B_CVR)
            elif mt == 'exact':
                role, prior = (bt['role'], bt['cvr_est']) if bt else ('Test', B2B_CVR)
            else:
                role, prior = 'Discovery', B2B_CVR
        cvr_kw = (od + PRIOR * prior) / (clk + PRIOR)
        # decision 162: a consumer exact keyword bids its search's own SQP price (its ad record no longer pulls it toward its
        # ad conversion); a broad, phrase or auto one the searches it served. Business keep their B2B record
        price_note, sv = None, None
        if SQP_PRICE and fam != 'Business':
            if mt == 'exact' and t:
                cvr_kw, price_note = t['cvr_price'], f"its search's own conversion ({t['price_basis']}, {t['cvr_price']:.1%})"
            elif mt != 'exact':
                sv = served_price(m.get('KeywordId'))
                if sv:
                    cvr_kw, price_note = sv[0], (f"the searches it served ({int(sv[1])} clicks on {sv[2]} search"
                                                 f"{'es' if sv[2] != 1 else ''}, each at its own SQP conversion: {sv[0]:.1%})")
        if fam == 'Business':
            idx_b = cvr_kw / t['market_cvr'] if t and t['market_cvr'] else None
        be_kw = PROFIT * cvr_kw
        tos = None
        sub = None
        recommendation = contextual.get(str(m.get('KeywordId')))
        suggestion = (tuple(recommendation[key] for key in ('low', 'median', 'high')) if recommendation
                      else tuple(sug.get(kw) or fallback_values.get(kw) or (None, None, None)))
        # a consumer invest search Amazon gave no suggestion for is priced on the fallback chain (decision 106)
        bid_fb = None if recommendation or kw in sug else fallback_sources.get(kw)
        if fam == 'Business':
            # a business keyword is priced and bounded on Amazon's suggestion read in a B2B ad group only
            # (suggested_bids_business.json, design 4h): a B2B auction prices differently, so a consumer suggestion never
            # stands in (the phase 1 shadow saw a consumer high cap a B2B bid below its breakeven). ctx.sug_b is set by
            # business.bid_pull
            recommendation, suggestion = None, tuple(ctx.sug_b.get(kw) or (None, None, None))
        # a paused keyword (or one of a paused campaign or ad group) is priced by its role like any other and then kept as
        # it is, its price written as a cut only (decision 155, inventory.paused): re-enabling it can't bring back an old bid
        paused_kw = bool(m.get('inventory_hold')) and not m.get('not_live') and bool(inv_cfg.get('paused'))
        if m.get('not_live'):
            action, new = 'Keep: not in the live read (archived or removed), so it is not priced', bid
        elif m.get('inventory_hold') and not paused_kw:
            action, new = 'Keep: its campaign, ad group or keyword is paused', bid
        elif fam == 'Business':
            # the business role prices the keyword inside the B2B campaign that holds it (design 4b), on the consumer
            # thresholds; never the exact SKC's duplicate, never moved into a consumer SKC. Rank: the owner (design 4c)
            # invests (its Business invest row below carries the bid, budget and top of search together), a copy pauses
            # while the owner invests (settled after the visibility review); with no owner that can invest, a copy keeps
            # its phase 1 price. Every other role: business.price
            owner = business_owner.get(kw)
            hi_b = suggestion[2] if mt == 'exact' else None   # the business suggested high still bounds an exact bid
            if role == 'Negate':
                action, new = 'Pause keyword (irrelevant search)', 0
            elif role == 'Rank' and owner is not None and str(owner.get('KeywordId')) == str(m.get('KeywordId')):
                sub = bt['sub_role']
                tos = plc['prove_tos_pct'] if sub == 'Prove first' else plc['invest_tos_pct']
                new, src = invest_bid_for(*suggestion, be_kw)
                new = round(min(new, hi_b), 2) if hi_b else new
                action = f"{sub}: bid to be visible ({src}), top-of-search +{tos}% (business)"
            elif role == 'Rank' and owner is not None:
                sub = bt['sub_role']
                action, new = BUSINESS_COPY_PAUSE, 0
                copy_price[str(m.get('KeywordId'))] = business.price(ctx, 'Rank', idx_b, clk, od, be_kw, hi_b)
            else:
                role, action, new = business.price(ctx, role, idx_b, clk, od, be_kw, hi_b)
        elif fam == 'Audience (low bids)':
            # an audience copy keeps its low bid, capped at its breakeven and never raised (decision 135: the AMC and
            # low-bid campaigns went from $10 to $45 a day once their hours opened at handover), at the non-rank share
            # (decision 139)
            nrk = nr_for(kw)
            if bid and bid > round(be_kw * nrk, 2):
                action, new = f'Audience: capped at {pct_words(nrk)}, never raised', round(be_kw * nrk, 2)
            else:
                action, new = f'Keep (audience campaign already bids at or below {pct_words(nrk)})', bid
        elif role == 'Negate':
            action, new = 'Pause keyword (irrelevant search)', 0
        elif role == 'Rank' and fam != 'SKC' and (kw in skc_terms or kw in live_skc):
            action, new = 'Pause here: the exact SKC owns this search', 0
        elif role == 'Rank':
            sub = t['sub_role']
            tos = plc['prove_tos_pct'] if sub == 'Prove first' else plc['invest_tos_pct']
            new, src = invest_bid_for(*suggestion, be_kw, bid_fb)
            action = f"{sub}: bid to be visible ({src}), top-of-search +{tos}%"
            if fam != 'SKC':
                action += '. Move into its own exact SKC'
        elif role in ('Defend', 'Test', 'Hold') and t and t.get('over_rank_cap') and mt == 'exact' and cap_low(kw):
            # a big search over the rank volume cap (decision 182; Kim 2026-11-04: "cut to amazon's suggested low ..
            # instead of breakeven"): the suggested low (Amazon's, else SoldScope's), never under breakeven, never raised
            target = round(max(be_kw * nr_for(kw), cap_low(kw)), 2)
            new = min(bid, target) if bid else target
            action = (f"Big search over the rank cap: suggested low ${cap_low(kw):.2f} ({cap_low_src(kw)}), never under "
                      f"breakeven ${be_kw * nr_for(kw):.2f}, never raised")
        elif role in ('Hold', 'Defend'):
            new, action = round(be_kw * nr_for(kw), 2), f'Hold at {pct_words(nr_for(kw))}'
            if (role == 'Hold' and hold_up and t and t.get('index') is not None
                    and hold_up['index_from'] <= t['index'] < hold_up['index_to']):
                # the Hold uplift test (Kim, 2026-10-23, decision 108; ended 2026-10-25): a Hold search at index 1.0-1.1
                # converts at or above the market, so its keywords bid breakeven +pct for more impressions
                new = round(be_kw * nr * (1 + hold_up['pct'] / 100), 2)
                action = f"Hold at breakeven +{hold_up['pct']:g}% (index {t['index']:.2f}, the Hold uplift test)"
        elif role in ('Test', 'Leave') and mt == 'exact' and season_now:
            # in season every search bids at its breakeven: its own conversion, with the 10-click prior toward the product's
            # (docs/seasonal-bidding.md section 3), not the market default a search without SQP gets as a Test, nor the low
            # holding bid of a search the search-term report has no orders for (B0SAMP0010 "thanksgiving sticker", dry run
            # 2026-10-21: 12 orders on 32 clicks as a keyword, $0.17 as Leave)
            new, action = round(be_kw, 2), f'Hold at breakeven (season: its own conversion, not a {role} bid)'
        elif role == 'Trim':
            if t and t['index'] < th['index_pause'] and clk >= th['pause_min_clicks']:
                new, action = 0, 'Pause: trails the market badly on 30+ clicks'
            else:
                new, action = round(max(th['trim_min_bid'], th['trim_factor'] * be_kw), 2), 'Trim to 70% of breakeven'
        elif role == 'Test':
            mk = (t or {}).get('market_cvr') or th['test_default_market_cvr']
            new, action = test_bid(PROFIT * mk, be_kw, nr_for(kw)), 'Test: economic starting bid; delivery must be validated'
        elif role == 'Discovery':
            cap = PROFIT * ASIN_AD_CVR
            # the cap lifts at 3 orders as it always did, and at discovery.cap_lift_orders (2) when the keyword's own conversion
            # is cap_lift_index (1.1 since decision 178; 1.25 before) or more times the product's ad conversion (data-stage design 4.4.5; Kim, 2026-10-21:
            # "pens colored" phrase, 2 orders on 8 clicks, holds about $0.42 instead of falling to the $0.19 cap)
            idx_kw = cvr_kw / ASIN_AD_CVR if ASIN_AD_CVR else None
            lifted_at_two = od < 3 and od >= dsc['cap_lift_orders'] and idx_kw is not None and at_least(idx_kw, dsc['cap_lift_index'])
            if sv:
                # decision 162: priced on the searches it served, so the product-average cap no longer applies
                new = round(be_kw * nr_for(kw), 2)
                action = f'Discovery: bid to {pct_words(nr_for(kw))} of the searches it served'
            else:
                new = round((be_kw if od >= 3 or lifted_at_two else min(be_kw, cap)) * nr_for(kw), 2)
                action = f'Discovery: bid to {pct_words(nr_for(kw))}' + ('' if od >= 3 else
                                                          f' (cap lifted: {int(od)} orders at index {idx_kw:.2f})' if lifted_at_two else
                                                          ' (capped at the product average)')
        else:
            new, action = round(PROFIT * th['leave_bid_cvr'], 2), 'Leave at a low bid'
        mid_info = None
        kid = str(m.get('KeywordId'))
        if (mid_state.get(kid) in mid_bid.MID_STATES and role in ('Hold', 'Test', 'Discovery') and fam != 'Business'
                and not action.startswith(('Pause', 'Keep')) and mid_owner.get((kw, mt)) == kid):
            # the suggested mid (decision 177): the mid itself, above or below breakeven, never the low or the high; 75% of it
            # on a search the product already ranks top 10 for. Its action keeps the role's word, so the change keeps its role
            mid, mid_src, mid_words = mid_value(kid, kw, mt, (sp / clk) if clk else None, clk)
            if mid:
                f = float(osh['top10_factor']) if kw in top10 else 1.0
                new = round(mid * f, 2)
                mid_info = dict(state=mid_state[kid], mid=mid, bid=new, source=mid_src, priced_on=mid_words, factor=f)
                action = (f"{role} at the suggested mid ({mid_words}" + (f', x{f:g}: the product ranks top 10 for it' if f != 1 else '')
                          + f'): {mid_bid.words(mid_state[kid], mid_cfg, ASIN_AD_CVR)}')
        # a keyword still in its launch test is left to finish it (decision 178): its test ends at 2 expected orders
        in_test = bool(mid_info) and mid_info['state'] in ('testing', 'extended')
        if (leak_pause and org_on and fam not in ('Business', 'Audience (low bids)') and role in ('Hold', 'Defend', 'Test', 'Discovery')
                and clk >= osh['leak_pause_clicks'] and not od and bid and not m.get('inventory_hold') and not in_test):
            # the leak check (decision 175): an ordinary keyword that spent 15+ clicks with no order pauses while the
            # product's ordinary campaigns lose money
            new, action = 0, f"Pause: leak check, {int(clk)} clicks and no orders while the ordinary keywords lose money"
            mid_info = None
        if brand(kw) and bid and new and new > bid and not action.startswith(('Pause', 'Keep')):
            # a brand keyword, any match type (a broad "yourbrand cards" too), is never raised: organic only
            new = round(bid, 2)
            action += ' (brand search: organic only, never raised)'
        if (never_raise and clk == 0 and role != 'Rank' and bid and new and new > bid and not mid_info
                and not action.startswith(('Pause', 'Keep', 'Audience'))):
            # no clicks of its own (decision 135): priced from its search's conversion, else the product's, and never
            # raised above its live bid on this run; once its hours are open, its own clicks decide
            new = round(bid, 2)
            action += ' (no clicks of its own: never raised on this run)'
        paused_price = None
        if paused_kw:
            # the rank logic still reads it as an inactive copy (decision 154): its action stays the paused Keep
            if role != 'Rank' and not action.startswith(('Pause', 'Keep')) and bid and new is not None and round(new, 2) < round(bid, 2):
                paused_price = (round(new, 2), action)
            action, new = 'Keep: its campaign, ad group or keyword is paused', bid
        lo_, med_, hi_ = suggestion if recommendation or mt == 'exact' else (None, None, None)
        plan.append(dict(asin=asin, keyword_id=str(m.get('KeywordId')), keyword=m['Keyword'], match=mt, family=fam, campaign=camp,
                         campaign_id=str(m.get('CampaignId')), ad_group_id=str(m.get('AdGroupId')), ad_group=m.get('AdGroupName'),
                         role=role, sub_role=sub, bid=bid, new_bid=new, tos_pct=tos, clicks90=int(clk), orders90=int(od),
                         spend90=round(sp, 2), sales90=round(sl, 2), cvr_used=round(cvr_kw, 4), breakeven_cpc=round(be_kw, 2),
                         suggested=(lo_, med_, hi_),
                         recommendation_source=('contextual' if recommendation else bid_fb[0] if bid_fb and med_
                                                else 'legacy_exact_proxy' if mt == 'exact' and med_ else 'missing'),
                         # the consumer invest log and rank experiments never hold a business keyword (another shopper's lane)
                         rank_investment_existing=mt == 'exact' and kw in retained_rank_terms and fam != 'Business',
                         inventory_only=m.get('inventory_only', False), strategy=(m.get('visibility_inventory') or {}).get('strategy'), action=action))
        if paused_price:
            plan[-1]['paused_price'] = paused_price
        if m.get('not_live'):
            plan[-1]['not_live'] = True
        elif m.get('inventory_hold'):
            # paused live (its keyword, ad group or campaign): a later row on it (a stop-loss step-down) must say so, or the
            # pre-write check reads the paused live keyword as drift (B0SAMP0006, 2026-11-04)
            plan[-1]['paused_live'] = True
        if mid_info:
            plan[-1]['mid_bid'] = mid_info
        elif mid_state.get(kid):
            plan[-1]['mid_state'] = mid_state[kid] if mid_owner.get((kw, mt), kid) == kid else 'copy'
        if price_note:
            plan[-1]['price_note'] = 'Priced on ' + price_note + ' (decision 162).'
        if fam == 'Business':
            # baseline_cvr is the pool, as in phase 1; prior_cvr the conversion this keyword was actually shrunk toward
            plan[-1].update(owner_kind='business', baseline_cvr=round(B2B_CVR, 4), prior_cvr=round(prior, 4))
        elif role == 'Rank' and bid_fb:
            plan[-1]['bid_source'] = bid_fb[0]
        if action.startswith('Hold at breakeven +'):
            plan[-1]['hold_uplift'] = hold_up['pct']
        elif (hold_up and role == 'Hold' and fam != 'Business' and t and t.get('index') is not None
              and t['index'] < hold_up['index_from']):
            plan[-1]['hold_comparison'] = True   # the test's comparison group: a Hold search at index 0.8-1.0 (decision 108)

    visibility_review = visibility.build_review(asin, plan, terms, visibility_inputs, visibility_policy, review_date) if visibility_policy.get('enabled') else None
    visibility_by_id = {row['keyword_id']: row for row in (visibility_review or {}).get('rows', [])}
    # a review holds a bid, and a rank search's investment, only on a check that came back "no" or a live experiment it
    # protects; a check it couldn't answer holds nothing (visibility.holds_bid; decision 107, 2026-10-23)
    # a paused or no-longer-live copy of a rank search is kept as it is (never written), but it doesn't hold the search's
    # investment while another copy of it is live: B0SAMP0023 2026-10-27, one paused exact copy of "highlighters pastel
    # colors" (index 1.64) kept the whole search at its live $0.35 (Kim, decision 154)
    def inactive_copy(row):
        return row['action'].startswith(('Keep: its campaign, ad group or keyword is paused', 'Keep: not in the live read'))
    rank_rows = [row for row in plan if row['role'] == 'Rank' and row['family'] not in ('Audience (low bids)', 'Business')]
    live_rank_terms = {norm(row['keyword']) for row in rank_rows if not inactive_copy(row)}
    deferred_bid_terms = {norm(row['keyword']) for row in rank_rows if
                          visibility.holds_bid(visibility_by_id.get(row['keyword_id'])) or
                          (row['action'].startswith('Keep') and not (inactive_copy(row) and norm(row['keyword']) in live_rank_terms))}
    deferred_bid_terms.update(set(rank_terms) & retained_rank_terms)
    # Scheduled OFF hours do not block base bids, but cannot prove a replacement is serving.
    scheduled_rank_terms = {norm(row['keyword']) for row in plan if row['role'] == 'Rank'
                            and row['family'] not in ('Audience (low bids)', 'Business')
                            and visibility_by_id.get(row['keyword_id'], {}).get('scheduled_pause')}
    deferred_rank_terms = deferred_bid_terms | scheduled_rank_terms
    if visibility_review is not None:
        visibility_review['retained_rank_searches'] = sorted(set(rank_terms) & retained_rank_terms)
    for row in plan:
        review = visibility_by_id.get(row['keyword_id'], {})
        # a consumer search's deferral (its retained investment, a guarded consumer keyword) never holds the business owner
        # of the same search; a business row's own visibility guard still does
        deferred = row['role'] == 'Rank' and row.get('owner_kind') != 'business' and norm(row['keyword']) in deferred_bid_terms
        routing_action = row['action'].startswith('Pause') or 'Move into its own exact SKC' in row['action']
        if norm(row['keyword']) in scheduled_rank_terms and row.get('owner_kind') != 'business' and routing_action:
            deferred = True
        if (visibility.holds_bid(review) or deferred) and not row['action'].startswith('Keep'):
            row['economic_base_bid'] = row['new_bid']
            row['new_bid'] = row['bid']
            row['action'] = 'Keep pending visibility review: ' + review.get('reason', 'delivery or retained experiment requires review')
        if review.get('scheduled_pause'):
            row['scheduled_pause'] = review['scheduled_pause']
    # a business copy pauses only while its owner invests (design 4c): when the owner doesn't (the visibility review keeps
    # its bid), the copy keeps its phase 1 price, so the search never loses its live B2B exact coverage
    business_investing = {norm(p['keyword']) for p in plan if p.get('owner_kind') == 'business' and p['role'] == 'Rank'
                          and p['action'].startswith(('Invest', 'Prove'))}
    for p in plan:
        if p['action'] == BUSINESS_COPY_PAUSE and norm(p['keyword']) not in business_investing:
            p['role'], p['action'], p['new_bid'] = copy_price[p['keyword_id']]
            p['sub_role'] = None

    # ---- 3. change list in launch order
    changes = []
    name = cfg.get('product') or asin

    def plan_role(p):
        """A keyword plan row's role as its change rows carry it (E1): an invest search's sub-role (Invest or Prove
        first), else its role (Trim, Negate, ...). A pause carries it too, so the lanes see what is being paused."""
        if p['role'] == 'Rank':
            return p.get('sub_role') or (terms.get(norm(p['keyword'])) or {}).get('sub_role')
        return p['role']

    def add(**kw):
        kw.setdefault('product', name)
        kw.setdefault('asin', asin)
        changes.append(kw)

    B2B_WHY = (f"Amazon Business campaign: priced on the B2B campaigns' own conversion ({B2B_CVR:.0%} pooled, "
               f"{PRIOR:g}-click prior), never on the consumer search.")

    def business_why(prior_cvr, search=None, role=True):
        """B2B_WHY naming the conversion a business row was priced on: an exact keyword's search's own business estimate
        (search given) with the pool beside it, else the pool alone. With role, the search's business role and its reason."""
        r = business_terms.get(search) if search else None
        if not r:
            return B2B_WHY
        text = (f"Amazon Business campaign: priced on the B2B campaigns' own conversion ({prior_cvr:.0%} on this search, "
                f"{B2B_CVR:.0%} pooled, {PRIOR:g}-click prior), never on the consumer search.")
        return text + (f" Its search's B2B role is {r['role']}: {r['why']}." if role else '')

    live_by_id = {str(c.get('campaignId')): c for c in camps}

    def live_budget_tos(cid):
        c = live_by_id.get(cid)
        if not c:
            return None, None, []
        adj = (((c.get('optimizations') or {}).get('bidSettings') or {}).get('bidAdjustments') or {}).get('placementBidAdjustments') or []
        tos = next((a['percentage'] for a in adj if a.get('placement') in ('TOP_OF_SEARCH', 'PLACEMENT_TOP')), 0)
        others = [a for a in adj if a.get('placement') not in ('TOP_OF_SEARCH', 'PLACEMENT_TOP')]
        return (c.get('budget') or {}).get('budget'), tos, others

    # the placement policy (Kim, 2026-10-27, decision 155; config placement.policy): a rank campaign takes the standing
    # rank top of search (step 6 below); every other Sponsored Products campaign of the product, enabled or paused, the older
    # human-launched ones and the "TOS 900%" experiments included, goes to non_rank_tos_pct (0%), its other placements as
    # live. Worked out here, before the bid rows, so a campaign whose boost can't come off this run (placement_review
    # .policy_blocker) prices its non-rank bids at price / (1 + boost): bid x boost never exceeds the price the role set
    pol = plc.get('policy') or {}
    policy_on = bool(pol.get('enabled')) and (pol.get('approved') or {}).get('by') == 'Kim'
    shape_conf = plc.get('shape') or {}
    experiment_ids = (placement_shape.experiment_campaigns(shape_conf.get('experiment_files'))[0]
                      if shape_conf.get('experiment_files') else set())
    experiment_markers = [m.lower() for m in shape_conf.get('experiment_name_markers') or []]

    def in_experiment(c):
        return (str(c.get('campaignId')) in experiment_ids
                or any(m in (c.get('name') or '').lower() for m in experiment_markers))
    # a rank campaign: an exact SKC whose search is invested in (any action, a held or deferred one too), retained in the
    # invest log or a season rank search, and a B2B campaign holding a business invest search
    rank_cids = {p['campaign_id'] for p in plan
                 if (p['family'] == 'SKC' and p['match'] == 'exact'
                     and (p['role'] == 'Rank' or norm(p['keyword']) in retained_rank_terms or norm(p['keyword']) in season_rank))
                 or (p.get('owner_kind') == 'business' and p['role'] == 'Rank')}
    policy_tos = {}    # campaign id -> its live top of search, for the campaigns the policy sets to non_rank_tos_pct
    kept_boost = {}    # campaign id -> the top-of-search boost it keeps this run (the write can't be made safely)
    if policy_on:
        target_pct = float(pol.get('non_rank_tos_pct') or 0)
        for c in camps:
            cid = str(c.get('campaignId'))
            if (c.get('state') or '').upper() not in ('ENABLED', 'PAUSED') or cid in rank_cids or in_experiment(c):
                continue
            _, t0, _ = live_budget_tos(cid)
            if not t0 or t0 <= target_pct:
                continue
            if placement_review.policy_blocker(c):
                kept_boost[cid] = t0
            else:
                policy_tos[cid] = t0
    boost_aware = policy_on and bool(pol.get('boost_aware', True))
    # the audience boost (Kim, 2026-10-27, decision 156): an AMC or other audience bid adjustment multiplies the bid for
    # the shoppers in that audience (+240% to +300% on the "AMC - Low Bids 0.25" campaigns, so a $0.25 bid paid about $0.85
    # before any placement boost). The planner keeps the adjustment and prices around it: a non-rank bid is price / (1 +
    # the campaign's largest audience boost), so an audience shopper's click never costs more than the price either
    audience_boost = {}
    if (plc.get('audience') or {}).get('price_around', True):
        for c in camps:
            adj = ((((c.get('optimizations') or {}).get('bidSettings') or {}).get('bidAdjustments') or {})
                   .get('audienceBidAdjustments') or [])
            top = max((num(a.get('percentage')) for a in adj if isinstance(a, dict)), default=0)
            if top > 0:
                audience_boost[str(c.get('campaignId'))] = top

    def boost_capped(cid, new, role):
        """A non-rank bid in a campaign that keeps a top-of-search boost this run, or carries an audience boost: price /
        ((1 + top of search) x (1 + audience)), and that combined boost in percent (None when there is none)."""
        t = kept_boost.get(str(cid)) if boost_aware else None
        a = audience_boost.get(str(cid))
        if not (t or a) or new is None or new <= 0 or role == 'Rank':
            return new, None
        factor = (1 + (t or 0) / 100) * (1 + (a or 0) / 100)
        return round(max(0.02, new / factor), 2), round((factor - 1) * 100, 1)

    def boost_words(cid):
        """The boost a bid is priced around, in words: '+30% top-of-search', '+255% audience' or both."""
        t = kept_boost.get(str(cid)) if boost_aware else None
        a = audience_boost.get(str(cid))
        parts = ([f'+{t:g}% top-of-search'] if t else []) + ([f'+{a:g}% audience'] if a else [])
        return ' and '.join(parts) + (' boosts' if len(parts) > 1 else ' boost')
    for p in plan:
        a = p['action']
        if a.startswith(('Pause', 'Keep')) or p['role'] == 'Rank' or p['new_bid'] is None:
            continue
        capped, t = boost_capped(p['campaign_id'], p['new_bid'], p['role'])
        if t and capped < p['new_bid']:
            p['priced_bid'], p['new_bid'], p['boost_kept'] = p['new_bid'], capped, t
            p['action'] = a + f' (÷ {1 + t / 100:g}: the campaign keeps a {boost_words(p["campaign_id"])} this run)'
            p['boost_words'] = boost_words(p['campaign_id'])

    if mode == 'onboard':
        add(step=1, type='Scale Insights rules', item='Take the bid rules off every ad group of this product',
            current='Whatever SI strategies are attached today (target-ACOS tiers, inch-ups, low-bid rules)',
            new='SI no-bid-rule strategies; exact SKCs on the exact-campaign owner strategy with the blacklist unassigned; invest searches whitelisted; effective dayparting 203 / 21246 on every AI-controlled SP/SB/SD group, replacing legacy direct schedules except approved schedule exceptions, assigned last, once every MAP bid of this plan is written and read back; shared exclusions unchanged; verify exact-ID coverage',
            why=('SI bid rules run every evening and would overwrite the AI bids within a day. The hours open last (decision 135): '
                 'a campaign the old schedule held to an hour a day spends all day at whatever bid it has once 203 opens it, '
                 'so every keyword and target is priced first.'),
            how='Scale Insights web app (Chrome). See references/onboarding.md')
    pc = cfg.get('price_change')
    if pc:
        add(step=2, type='Listing price', item=f"Price, SKU {cfg['sku']}", current=pc.get('from'), new=pc.get('to'), why=pc.get('why', ''),
            how='MarketplaceAdPros update_listing (amazon_preview first)')

    prefix = cfg['campaign_prefix']
    new_terms = {}
    for t in rank_terms:
        if t in deferred_rank_terms:
            continue
        # an audience copy or a business campaign never stands in for the consumer owner of a search
        if t not in skc_terms and t not in live_skc and not any(norm(p['keyword']) == t and p['match'] == 'exact'
                                                                    and p['family'] not in ('Audience (low bids)', 'Business') for p in plan):
            new_terms[t] = 'new search'
    moved = [p for p in plan if 'Move into its own exact SKC' in p['action']]
    for p in moved:
        new_terms.setdefault(norm(p['keyword']), f"moved from {p['family']}")
    reuse = {}
    for t in rank_terms:
        if t in deferred_rank_terms:
            continue
        if t in live_skc and t not in skc_terms:
            reuse[t] = live_skc[t]
            new_terms.pop(t, None)
    def fallback_why(t):
        # a search Amazon gave no suggested bid for says what its bid was priced on (bid_fallback; decision 106)
        return f" Amazon gave no suggested bid, so it is priced on {fallback_sources[t][1]}." if t in fallback_sources else ''

    def fallback_field(t):
        return dict(bid_source=fallback_sources[t][0]) if t in fallback_sources else {}

    for t, src in sorted(new_terms.items()):
        r = terms[t]
        sub = r['sub_role']
        lo, med, hi = rank_suggestions.get(t, (None, None, None))
        be = r['be_cpc']
        bid = round(invest_bid_unrounded(med, hi, be), 2)
        tos = plc['prove_tos_pct'] if sub == 'Prove first' else plc['invest_tos_pct']
        budget = invest_budget(t, sub)
        add(step=3, type='New exact campaign', keyword=t, role=sub, campaign=prefix + 'Exact SKC - ' + t + ' - TOS Rank',
            current=None, new=bid, tos=tos, tos_bid=round(bid * (1 + tos / 100), 2), budget=budget,
            sug_low=lo, sug_median=med, sug_high=hi, source=src, evidence=evidence_text(r),
            why=("Beats the market on enough data: Amazon's suggested median, or breakeven if higher, never above the high."
                 if sub == 'Invest' else 'Beats the market on fewer than 3 purchases: smaller budget and boost until it proves itself.')
                + fallback_why(t), **fallback_field(t),
            how=f'MAP create: campaign (manual, ${budget}/day, down only, top of search +{tos}%, portfolio {shared["portfolio_id"]}), '
                f'ad group "Performance Exact", product ad {cfg["sku"]}, exact keyword')
    for t, c in sorted(reuse.items()):
        r = terms[t]
        sub = r['sub_role']
        lo, med, hi = rank_suggestions.get(t, (None, None, None))
        bid = round(invest_bid_unrounded(med, hi, r['be_cpc']), 2)
        tos = plc['prove_tos_pct'] if sub == 'Prove first' else plc['invest_tos_pct']
        budget = invest_budget(t, sub)
        add(step=3, type='Reuse exact campaign', keyword=t, role=sub, campaign=c.get('name'), campaign_id=str(c.get('campaignId')),
            current=None, new=bid, tos=tos, tos_bid=round(bid * (1 + tos / 100), 2), budget=budget,
            budget_now=(c.get('budget') or {}).get('budget'), sug_low=lo, sug_median=med, sug_high=hi, source='existing idle SKC',
            evidence=evidence_text(r),
            why='An exact campaign for this search already exists but sat idle (no spend in 90 days). Reuse it instead of creating a duplicate.'
                + fallback_why(t), **fallback_field(t),
            how='MAP: list its exact keyword (sp_keywords campaign_id) and set the bid; update budget + top of search; '
                'check its ad group for self-blocking negatives (references/live-checks.md)')

    # the business invests (business.promotion_rows and new_keyword_rows; design 4b, 4c): a Business invest row per owner
    # keyword that invests, inside the team's B2B campaign that holds it, and a New exact keyword row per business invest
    # search no B2B exact keyword holds
    ctx.plan, ctx.changes, ctx.live_budget_tos, ctx.invest_budget = plan, changes, live_budget_tos, invest_budget
    ctx.business_why = business_why
    business_live = business.promotion_rows(ctx, add)
    ctx.business_live, ctx.invest_bid_for = business_live, invest_bid_for
    business.new_keyword_rows(ctx, add)

    # the B2B Scale Insights rules row (business.scale_insights_row; design 4h), before the pauses and funnel negatives
    business.scale_insights_row(ctx, add)
    # consolidate before adding (Kim, 2026-10-25, decision 135, fix 7 of the AI spend review): a copy whose search gets its
    # own exact campaign this run drops to a low holding bid the same day, so the old copy and the new campaign don't both
    # spend on the search while the pause waits for the new campaign to serve (the serving gate). Never raised, never under
    # the minimum bid; the pause row below is unchanged
    copy_hold_cvr = inv_cfg.get('copy_holding_bid_cvr')

    def holding_bid(floor):
        return round(max(floor, PROFIT * copy_hold_cvr), 2)

    for p in moved:
        add(step=4, type='Pause keyword', keyword=norm(p['keyword']), match=p['match'], role=plan_role(p), campaign=p['campaign'],
            current=p['bid'], new=None, why='Moves to its own exact campaign (step 3), so one campaign owns the search.',
            clicks90=p['clicks90'], orders90=p['orders90'], spend90=p['spend90'],
            keyword_id=p['keyword_id'], campaign_id=p['campaign_id'], ad_group_id=p['ad_group_id'],
            how='MAP update sp_keywords: state PAUSED')
        if copy_hold_cvr is None or not p['bid'] or round(p['bid'], 2) <= holding_bid(th['trim_min_bid']):
            continue
        hb = holding_bid(th['trim_min_bid'])
        add(step=5, type='Bid change', keyword=norm(p['keyword']), match=p['match'], family=p['family'], role=plan_role(p),
            campaign=p['campaign'], current=round(p['bid'], 2), new=hb, change=round(hb / p['bid'] - 1, 3),
            clicks90=p['clicks90'], orders90=p['orders90'], spend90=p['spend90'], cvr=p['cvr_used'], breakeven=p['breakeven_cpc'],
            sug_low=None, sug_median=None, sug_high=None, visibility=None, copy_hold=True,
            why=(f"Copy of a search its own exact campaign takes over this run (step 3): held at a low bid (${hb:.2f}, "
                 f"{copy_hold_cvr:.0%} x profit per unit) from today so the old copy and the new campaign don't both spend "
                 'on it, and paused once the new campaign serves (decision 135).'),
            keyword_id=p['keyword_id'], campaign_id=p['campaign_id'], ad_group_id=p['ad_group_id'], how='MAP update sp_keywords: bid')
    for p in plan:
        if not p['action'].startswith('Pause'):
            continue
        why = ('An exact campaign already owns this search.' if 'owns' in p['action'] else
               'The business owner (the B2B exact keyword with the most clicks) holds this search: one owner per search '
               'inside the business kind.' if 'business owner holds' in p['action'] else
               'Irrelevant search for this product.' if 'irrelevant' in p['action'] else
               (f"Leak check (decision 175): {p['clicks90']} clicks and no orders in 90 days while the product's ordinary "
                f"campaigns lost money over the last {osh['leak_days']} settled days." if 'leak check' in p['action'] else
                'Converts well under the market on 30+ clicks.'))
        biz = dict(owner_kind='business') if p.get('owner_kind') == 'business' else {}
        if biz:
            why = f'{B2B_WHY} {why}'
        # the 90-day counts let the lanes see a pause of a keyword that has orders (always a person's call)
        add(step=4, type='Pause keyword', keyword=norm(p['keyword']), match=p['match'], role=plan_role(p), campaign=p['campaign'],
            current=p['bid'], new=None, why=why, clicks90=p['clicks90'], orders90=p['orders90'], spend90=p['spend90'],
            keyword_id=p['keyword_id'], campaign_id=p['campaign_id'], ad_group_id=p['ad_group_id'],
            how='MAP update sp_keywords: state PAUSED', **biz)

    share = '' if nr == 1 else f' Not a rank search, so it bids {nr:.0%} of breakeven (decision 139).'
    WHY = {'Rank': "Invest search: Amazon's suggested median, or breakeven if higher, never above the high; top-of-search boost in step 6.",
           'Hold': 'Converts at the market: its breakeven click.' + share,
           'Trim': 'Trails the market on 15+ clicks: 70% of breakeven.',
           'Test': 'Economic starting bid, not a visibility guarantee; validate delivery and evidence.' + share,
           'Discovery': 'Broad, phrase or auto: breakeven at its own conversion, capped at the product average until it has 3 orders, '
                        'or 2 orders at a keyword index of 1.1+ against the product\'s ad conversion.' + share,
           'Other': 'Small search with no data: a low holding bid.',
           'Big': '',
           'Audience': 'Audience campaign: keeps its low bid, capped at its breakeven click and never raised.' + share}
    seen_ids = set()
    for p in plan:
        seen_ids.add(p['keyword_id'])
        a = p['action']
        if a.startswith(('Pause', 'Keep')) or 'Move into its own exact SKC' in a:
            continue
        if p.get('owner_kind') == 'business' and p['role'] == 'Rank':
            continue   # the business owner's Business invest row (step 3) is its whole change (design 4b)
        if p['bid'] is None or p['new_bid'] is None or round(p['bid'], 2) == round(p['new_bid'], 2):
            continue
        g = ('Rank' if a.startswith(('Invest', 'Prove')) else 'Big' if a.startswith('Big search') else 'Hold' if a.startswith('Hold') else 'Trim' if a.startswith('Trim')
             else 'Test' if a.startswith('Test') else 'Discovery' if a.startswith('Discovery')
             else 'Audience' if a.startswith('Audience') else 'Other')
        role = p['sub_role'] if g == 'Rank' else {'Other': 'Low bid', 'Audience': 'Audience cap', 'Big': 'Defend'}.get(g, g)
        lo_, med_, hi_ = p['suggested']
        why = (f"{a} (decision 182): rank money goes to searches under the cap, and this one keeps some visibility at the "
               "suggested low, with top of search at 0%." if g == 'Big' else WHY[g]) + (' Harvested keyword, now priced by its role.' if p['family'] == 'Harvest' else '')
        mb = p.get('mid_bid')
        if mb:
            why = (f"{g} keyword {mid_bid.words(mb['state'], mid_cfg, ASIN_AD_CVR)}: it bids the suggested mid, {mb['priced_on']}, not its "
                   f"breakeven click (${p['breakeven_cpc']:.2f}), never Amazon's low or high and with no top-of-search boost "
                   '(decision 177).' + (f" The product already ranks for this search organically "
                                       f"({top10.get(norm(p['keyword']))}), so it bids {mb['factor']:.0%} of the mid." if mb['factor'] != 1 else ''))
        elif g in ('Hold', 'Test', 'Discovery', 'Audience') and norm(p['keyword']) in top10 and p.get('owner_kind') != 'business':
            why += (f" The product already ranks for this search organically ({top10[norm(p['keyword'])]}), so it bids "
                    f"{nr_for(norm(p['keyword'])):.0%} of breakeven (the top-10 rule, decisions 143 and 175).")
        if p.get('scheduled_pause'):
            why += ' Verified dayparting OFF period; base bid can be prepared without enabling the ad group or changing its schedule.'
        if p.get('boost_kept'):
            biz_boost = dict(priced_bid=p['priced_bid'], boost_kept=p['boost_kept'])
            words = p.get('boost_words') or f"+{p['boost_kept']:g}% top-of-search boost"
            why += (f" Priced ${p['priced_bid']:.2f}; its campaign keeps a {words} this run, so it bids ${p['new_bid']:.2f} "
                    'and a boosted click still costs no more than the price (placement policy, decision 155; audience '
                    'boosts, decision 156).')
        else:
            biz_boost = {}
        if p.get('inventory_only') and not p['clicks90']:
            why += (' No 90-day row in Scale Insights: priced from the live keyword list on its search\'s conversion, else the '
                    'product\'s (decision 135).')
        biz = {}
        if g == 'Discovery' and '(cap lifted: ' in a:
            # the Discovery cap lift (rulebook 10.3, item 5) is named on the row itself, not only in the keyword plan's
            # action, which write_outputs drops from plan.json: the preview, the dashboard and the log read the row's why
            # and its cap_lifted field (final review, 2026-10-22)
            lift = a.split('(cap lifted: ', 1)[1].rstrip(')')
            why += f" Cap lifted here: {lift} against the product's ad conversion, so it bids its own breakeven."
            biz = dict(cap_lifted=lift)
        if p.get('owner_kind') == 'business':
            why = business_why(p['prior_cvr'], norm(p['keyword']) if p['match'] == 'exact' else None)
            biz = dict(owner_kind='business', baseline_cvr=p['baseline_cvr'], prior_cvr=p['prior_cvr'])
        if p.get('bid_source') and g == 'Rank':
            biz['bid_source'] = p['bid_source']
        if p.get('hold_uplift') and g == 'Hold':
            biz['hold_uplift'] = p['hold_uplift']
            why += (f" Its search's index is 1.0-1.1, so it bids breakeven +{p['hold_uplift']:g}%: the Hold uplift test "
                    f"to {hold_up.get('review_on')} (decision 108).")
        if p.get('price_note') and p.get('owner_kind') != 'business' and not mb:
            why += ' ' + p['price_note']
        if mb:
            biz['mid_bid'] = mb
        add(step=5, type='Bid change', keyword=norm(p['keyword']), match=p['match'], family=p['family'], role=role, campaign=p['campaign'],
            current=round(p['bid'], 2), new=round(p['new_bid'], 2), change=round(p['new_bid'] / p['bid'] - 1, 3) if p['bid'] else None,
            clicks90=p['clicks90'], orders90=p['orders90'], spend90=p['spend90'], cvr=p['cvr_used'], breakeven=p['breakeven_cpc'],
            sug_low=lo_, sug_median=med_, sug_high=hi_, visibility=visibility_by_id.get(p['keyword_id']), why=why,
            keyword_id=p['keyword_id'], campaign_id=p['campaign_id'], ad_group_id=p['ad_group_id'], how='MAP update sp_keywords: bid',
            **biz, **biz_boost)

    # paused keywords (decision 155, inventory.paused): priced by their role above, written as a cut only and left paused, so
    # turning a campaign, ad group or keyword back on can't bring back an old launch bid
    for p in plan:
        if not p.get('paused_price') or p['keyword_id'] in {x.get('keyword_id') for x in changes if x['type'] == 'Bid change'}:
            continue
        new, priced = p['paused_price']
        new = min(new, *(x for x in [p['bid']] if x))
        capped, t = boost_capped(p['campaign_id'], new, p['role'])
        boost = dict(priced_bid=new, boost_kept=t) if t and capped < new else {}
        new = capped if boost else new
        add(step=5, type='Bid change', keyword=norm(p['keyword']), match=p['match'], family=p['family'],
            role=plan_role(p) or p['role'], campaign=p['campaign'], current=round(p['bid'], 2), new=round(new, 2),
            change=round(new / p['bid'] - 1, 3), clicks90=p['clicks90'], orders90=p['orders90'], spend90=p['spend90'],
            cvr=p['cvr_used'], breakeven=p['breakeven_cpc'], sug_low=None, sug_median=None, sug_high=None, paused=True,
            why=(f"Paused: priced now as it would bid ({priced}), cut only, so turning its campaign, ad group or keyword back "
                 "on can't bring back an old bid. It stays paused (decision 155)."
                 + (f" Its campaign keeps a {boost_words(p['campaign_id'])} this run, so it bids price / {1 + t / 100:g}." if boost else '')),
            keyword_id=p['keyword_id'], campaign_id=p['campaign_id'], ad_group_id=p['ad_group_id'],
            how='MAP update sp_keywords: bid (the keyword stays paused)', **(dict(owner_kind='business') if p.get('owner_kind') == 'business' else {}),
            **boost)

    # out-of-plan sweep: keywords that spent in the last days but had no 90-day data (dormant high bids)
    for r in recent:
        kid = str(r.get('keywordId'))
        if kid in seen_ids or not r.get('keyword'):
            continue
        mt = (r.get('matchType') or '').lower()
        if mt.startswith('targeting'):
            continue
        cur = num(r.get('bid'))
        kw = norm(r['keyword'])
        t = terms.get(kw)
        rk = kind(r.get('campaignName'))
        if rk != 'consumer':
            # an audience or B2B copy's dormant keyword (decision 155; until 2026-10-27 the sweep left them out): capped at
            # its breakeven on the product's ad conversion (the B2B pool's for business) x the non-rank share, cut only
            new = round(PROFIT * (B2B_CVR if rk == 'business' else ASIN_AD_CVR) * nr, 2)
            if cur and new < cur:
                add(step=5, type='Bid change', keyword=kw, match=mt, family=family(r.get('campaignName')),
                    role='Business cap' if rk == 'business' else 'Audience cap', campaign=r.get('campaignName'),
                    current=round(cur, 2), new=new, change=round(new / cur - 1, 3), clicks90=int(num(r.get('clk'))),
                    orders90=int(num(r.get('ord'))), spend90=round(num(r.get('cost')), 2), cvr=None, breakeven=None, sug_low=None,
                    sug_median=None, sug_high=None,
                    why=(f"Out of plan: an {'Amazon Business' if rk == 'business' else 'audience'} copy's keyword spent in the last "
                         f'days with no 90-day history (a dormant bid woke up): capped at {nr_words}, never raised (decision 155).'),
                    keyword_id=kid, campaign_id=None, ad_group_id=None, how='MAP update sp_keywords: bid',
                    **(dict(owner_kind='business') if rk == 'business' else {}))
            continue
        if mt == 'exact':
            mk = (t or {}).get('market_cvr') or th['test_default_market_cvr']
            new, role = test_bid(PROFIT * mk, PROFIT * ((t or {}).get('cvr_est') or ASIN_AD_CVR)), 'Test'
        else:
            new, role = round(PROFIT * ASIN_AD_CVR * nr, 2), 'Discovery'
        if cur and new < cur:
            add(step=5, type='Bid change', keyword=kw, match=mt, family=family(r.get('campaignName')), role=role, campaign=r.get('campaignName'),
                current=round(cur, 2), new=new, change=round(new / cur - 1, 3), clicks90=int(num(r.get('clk'))), orders90=int(num(r.get('ord'))),
                spend90=round(num(r.get('cost')), 2), cvr=None, breakeven=None, sug_low=None, sug_median=None, sug_high=None,
                why='Out of plan: spent in the last days with no 90-day history (a dormant bid woke up). Priced by the same rules.',
                keyword_id=kid, campaign_id=None, ad_group_id=None, how='MAP update sp_keywords: bid')

    # ---- product targets (Sponsored Products ASIN, category and auto targets, and Sponsored Display targets; rulebook
    #      section 2b)
    # No SQP exists for a target, so a target is judged against the product's own ad conversion (a Sponsored Display one
    # against the product's own display conversion), with the same 10-click prior as keywords. Campaigns that carry a
    # placement experiment in their name (e.g. "TOS 900%") are left alone: a breakeven bid there would be multiplied by the
    # boost. Business campaigns are not priced as consumer targets; an audience copy's target is capped at its breakeven and
    # never raised, like its keywords. Since 2026-10-25 (decision 135) auto targets and Sponsored Display CPC targets are
    # priced too, the live target list adds the ones with no 90-day row, and a target with no clicks of its own is never
    # raised on that run
    tcfg = shared.get('targets') or {}
    # every target read, priced or not, with what the plan does to its bid (placement_shape.py reads it: a campaign's
    # base bids can be shaped only when every serving bid of it is known)
    target_plan = []
    targets_seen = 0
    target_counts = Counter()
    sd_status, live_t_counts = 'off', {}
    if tcfg.get('enabled', True):
        si_targets = load_targets(run, asin, auto=tcfg.get('auto_targets', False), scope=scope)
        daypart_out['targets'] = rebase_live(live_inv['targets'], {str(r.get('TargetId')): num(r.get('Bid')) for r in si_targets
                                                                   if r.get('Bid') not in (None, '')}, 'targetId', daypart_m)
        sp_targets, live_t_counts = merge_live_targets(si_targets, live_inv['targets'], camps, tcfg.get('auto_targets', False),
                                                       paused=bool(tcfg.get('paused')))
        sd_targets = []
        if tcfg.get('sd'):
            sd_targets, sd_status, _ = load_sd_targets(run, asin, tuple(tcfg.get('sd_skip_cost_types') or ('vcpm',)), scope)
        # the product's own display conversion: its SD targets' pooled orders and clicks, shrunk toward its ad conversion
        sd_clk = sum(num(m.get('Clicks')) for m in sd_targets)
        sd_od = sum(num(m.get('Orders')) for m in sd_targets)
        SD_CVR = (sd_od + PRIOR * ASIN_AD_CVR) / (sd_clk + PRIOR)
        for m in sp_targets + sd_targets:
            camp = m.get('CampaignName') or ''
            ad = 'SD' if m.get('AdType') == 'SD' else 'SP'
            res = 'sd_targets' if ad == 'SD' else 'sp_targets'
            ckind = kind(camp)
            rec = dict(ad_product=ad, target_id=str(m.get('TargetId')), campaign_id=str(m.get('CampaignId')),
                       ad_group_id=str(m.get('AdGroupId')), bid=num(m.get('Bid')) if m.get('Bid') not in (None, '') else None,
                       new=None, status='skipped')
            target_plan.append(rec)
            # a business (B2B) target is priced on the B2B campaigns' conversion, cut only (decision 155: until 2026-10-27
            # business targets were left out); a target in a campaign config targets.skip_campaign_markers names is skipped
            if (ckind == 'business' and not tcfg.get('business', True)) or any(x in camp for x in tcfg.get('skip_campaign_markers', [])):
                continue
            # a paused target, or one of a paused campaign or ad group, is priced cut only (decision 155, targets.paused), so
            # turning it back on can't bring back an old launch bid; with targets.paused false it is kept as it is
            paused = bool(m.get('inventory_hold'))
            if paused and not tcfg.get('paused'):
                target_counts['paused'] += 1
                rec['status'] = 'paused'
                continue
            bid = num(m.get('Bid')) if m.get('Bid') not in (None, '') else None
            if not bid:
                target_counts['no bid of its own'] += 1
                rec['status'] = 'no bid of its own'
                continue
            targets_seen += 1
            ttype = m.get('TargetType') or 'product'
            target_counts[f"{ad} {ttype}" + (' paused' if paused else '')] += 1
            base = SD_CVR if ad == 'SD' else B2B_CVR if ckind == 'business' else ASIN_AD_CVR
            base_words = ("the product's display conversion" if ad == 'SD' else "the B2B campaigns' conversion"
                          if ckind == 'business' else "the product's ad average")
            cap_t = PROFIT * base
            clk, od, sp_ = num(m.get('Clicks')), num(m.get('Orders')), num(m.get('Spend'))
            cvr_t = (od + PRIOR * base) / (clk + PRIOR)
            be_t = PROFIT * cvr_t
            idx_t = cvr_t / base if base else 1.0
            text = m.get('TargetText') or ''
            ids = dict(target_id=str(m.get('TargetId')), campaign_id=str(m.get('CampaignId')), ad_group_id=str(m.get('AdGroupId')))
            extra = dict(ad_product='SD') if ad == 'SD' else {}
            if ckind == 'consumer' and not paused and od == 0 and clk >= tcfg.get('pause_min_clicks', th['pause_min_clicks']):
                add(step=4, type='Pause target', keyword=text, match=ttype, role='Pause', campaign=camp,
                    current=round(bid, 2), new=None, clicks90=int(clk), orders90=0, spend90=round(sp_, 2), baseline_cvr=round(base, 4),
                    why=f"No order on {int(clk)} clicks.",
                    how=f"MAP update {res}: state {'paused' if ad == 'SD' else 'PAUSED'}", **ids, **extra)
                rec['status'] = 'pause'
                continue
            if ckind == 'audience':
                role, new = 'Audience cap', min(bid, be_t * nr)
                why = f"Audience campaign: keeps its low bid, capped at {nr_words} and never raised."
            elif ckind == 'business':
                role, new = 'Business cap', min(bid, be_t * nr)
                why = (f"Amazon Business campaign: priced on the B2B campaigns' own conversion ({B2B_CVR:.0%} pooled, "
                       f"{PRIOR:g}-click prior), capped at {nr_words} and never raised (decision 155).")
            elif clk >= th['trim_min_clicks'] and idx_t < th['index_hold']:
                role, new = 'Trim', max(th['trim_min_bid'], th['trim_factor'] * be_t)
                why = f"Converts at {idx_t:.2f}x {base_words} on {int(clk)} clicks: 70% of its breakeven click."
            elif od >= tcfg.get('proven_orders', 3):
                role, new = 'Hold', be_t * nr
                why = f"{int(od)} orders on {int(clk)} clicks: {'its breakeven click' if nr == 1 else nr_words + ' (decision 139)'}."
            else:
                role, new = 'Test', min(be_t, cap_t) * nr
                why = (f"Not enough orders to judge: breakeven at its own conversion, capped at {base_words}'s breakeven click "
                       "until it has 3 orders" + ('.' if nr == 1 else f', at {nr:.0%} (decision 139).'))
            new = round(max(th['trim_min_bid'], new), 2)
            boost = {}
            if ad == 'SP':
                capped, t = boost_capped(m.get('CampaignId'), new, role)
                if t and capped < new:
                    # the campaign keeps a top-of-search boost this run (placement policy, decision 155): price / (1 + boost),
                    # never under Amazon's $0.02
                    boost = dict(priced_bid=new, boost_kept=t)
                    new = round(max(0.02, capped), 2)
                    why += (f" Priced ${boost['priced_bid']:.2f}; its campaign keeps a {boost_words(m.get('CampaignId'))} this run, so "
                            f"it bids ${new:.2f} and a boosted click still costs no more than the price (decisions 155 and 156).")
            if paused and new > bid:
                new = round(bid, 2)   # a paused target is cut only
            rec.update(status='kept', new=round(bid, 2))
            if never_raise and clk == 0 and new > bid:
                target_counts['no clicks, kept'] += 1
                continue   # no clicks of its own (decision 135): never raised on this run
            if round(bid, 2) == new:
                continue
            rec.update(status='priced', new=new)
            if ad == 'SD':
                why += f" Sponsored Display: judged on the product's display conversion ({SD_CVR:.1%}, {int(sd_od)} orders on {int(sd_clk)} clicks, {PRIOR:g}-click prior)."
            if m.get('live_only'):
                why += ' No 90-day row in Scale Insights: priced from the live target list (decision 135).'
            if paused:
                extra = dict(extra, paused=True)
                why += (" Paused: priced now, cut only, so turning it back on can't bring back an old bid; it stays paused "
                        '(decision 155).')
            add(step=5, type='Target bid change', keyword=text, match=ttype, family=family(camp), role=role,
                campaign=camp, current=round(bid, 2), new=new, change=round(new / bid - 1, 3), clicks90=int(clk), orders90=int(od),
                spend90=round(sp_, 2), cvr=round(cvr_t, 4), breakeven=round(be_t, 2), baseline_cvr=round(base, 4), why=why,
                how=f'MAP update {res}: bid', **ids, **extra, **boost)

    # budget headroom (Kim, 2026-10-20): the product's campaigns that run out of budget at a profit get a budget step, and a
    # step that stopped paying goes back (scripts/budget_headroom.py). Since 2026-10-31 (decision 174) the rank campaigns
    # (Invest, Prove first) are judged too, without the ACOS condition: one that runs out of budget steps up (never past
    # max_budget), and the rank budget below keeps a step the ledger recorded, so the standard never undoes it. The B2B
    # campaigns that hold a business invest this run keep their invest's budget (business_invested: their invest row, or the
    # live invest, sets it); the other B2B campaigns are judged like consumer ones (design 2026-10-21-b2b-lane-and-roles 4e);
    # the audience copies get no step, left as they are until phase 2. ctx.business_invested is set by
    # business.new_keyword_rows
    invest_ids = {str(p['campaign_id']) for p in plan if p['family'] == 'SKC' and p['action'].startswith(('Invest', 'Prove'))
                  and p.get('campaign_id')}
    headroom_excluded = ((set(ctx.business_invested)
                          | {str(c.get('campaignId')) for c in camps if kind(c.get('name')) == 'audience'}) - invest_ids)
    bh_rows, bh_summary = budget_headroom.plan_rows(run, asin, cfg, shared, dt.date.fromisoformat(review_date), camps,
                                                    headroom_excluded, rank=invest_ids)
    rank_step = {str(r['campaign_id']): r for r in bh_rows if r.get('rank_campaign') and r['direction'] == 'up'}
    stepped = {cid: float(st['to']) for cid, st in budget_headroom.last_steps(budget_headroom.load_ledger(
        budget_headroom.ledger_path(shared))).items() if st.get('to') is not None}

    for p in plan:
        if p['family'] != 'SKC' or not p['action'].startswith(('Invest', 'Prove')) or p.get('scheduled_pause'):
            continue
        kw = norm(p['keyword'])
        sub = p['sub_role']
        budget = invest_budget(kw, sub)
        b0, t0, others = live_budget_tos(p['campaign_id'])
        cid = str(p.get('campaign_id'))
        kept = stepped.get(cid)
        step_row = rank_step.get(cid)
        extra_why = ''
        if step_row is not None and step_row['budget'] > budget:
            budget = step_row['budget']
            extra_why = f" Budget step: {step_row['why']}."
        elif kept is not None and b0 is not None and kept > budget and abs(b0 - kept) < 0.005:
            budget = kept   # a budget step the ledger recorded stays: the standard never undoes it (decision 174)
            extra_why = f' Keeps its ${kept:g}/day budget step (budget headroom, decision 174).'
        if b0 == budget and t0 == p['tos_pct']:
            continue
        folded = step_row is not None and t0 != p['tos_pct']
        if folded:
            # one budget row per campaign: the step rides on this row (log_invest records it from budget_step_folded)
            bh_rows.remove(step_row)
            rank_step.pop(cid)
        elif step_row is not None:
            continue   # only the budget moves: the Budget step row carries it
        add(step=6, type='Budget and top of search', keyword=kw, role=sub, campaign=p['campaign'], budget_now=b0, budget=budget,
            tos_now=t0, tos=p['tos_pct'], campaign_id=p['campaign_id'], other_placements=others,
            **({'rank_budget_step': budget} if budget > invest_budget(kw, sub) else {}),
            **({'budget_step_folded': True} if folded else {}),
            why=f"{sub} campaign: ${budget:g}/day so the search can take the clicks it needs; top of search converts best on these products.{extra_why}",
            how='MAP update sp_campaigns: budget + complete dynamicBidding (send every existing placement)')

    # a seasonal product: an exact SKC that isn't one of this phase's rank searches (none is, in wake and harvest) has its
    # top-of-search boost taken off, so its breakeven bid isn't multiplied at the top of search. Budget unchanged; always
    # a person's call (placement_review.hold_defaults keeps the live boost where the write can't be made safely)
    if season_now:
        boost_off = set()
        for p in plan:
            cid = p['campaign_id']
            if (p['family'] != 'SKC' or p['match'] != 'exact' or norm(p['keyword']) in season_rank or cid in boost_off
                    or p['action'].startswith('Pause')):
                continue
            b0, t0, others = live_budget_tos(cid)
            if not t0:
                continue
            boost_off.add(cid)
            add(step=6, type='Budget and top of search', keyword=norm(p['keyword']), role=plan_role(p), campaign=p['campaign'],
                budget_now=b0, budget=b0, tos_now=t0, tos=0, campaign_id=cid, other_placements=others, season_harvest=True,
                why=f"Season {season_now['phase']}: no top-of-search push on a search that isn't invested in; a +{t0:g}% boost "
                    f"would pay more than its breakeven click at the top of search (docs/seasonal-bidding.md).",
                how='MAP update sp_campaigns: budget unchanged + complete dynamicBidding, top of search 0% (send every existing placement)')

    # the placement policy's rows (decision 155, worked out before the bid rows): every non-rank campaign that carries a
    # top-of-search boost goes to non_rank_tos_pct, budget unchanged, its other placements as live. Applies on its own: it
    # can only lower bids. placement_review.hold_defaults checks the write again and holds it where it can't be made safely
    done_cids = {str(x.get('campaign_id')) for x in changes if x['type'] == 'Budget and top of search'}
    for cid, t0 in sorted(policy_tos.items()):
        if cid in done_cids:
            continue
        c = live_by_id[cid]
        b0, _, others = live_budget_tos(cid)
        add(step=6, type='Budget and top of search', keyword=None, role='Placement policy', campaign=c.get('name'), budget_now=b0,
            budget=b0, tos_now=t0, tos=float(pol.get('non_rank_tos_pct') or 0), campaign_id=cid, other_placements=others,
            placement_policy=True, campaign_state=(c.get('state') or '').upper(),
            why=(f"Placement policy (decision 155): not a rank campaign, so top of search goes from +{t0:g}% to "
                 f"{float(pol.get('non_rank_tos_pct') or 0):g}%. The planner prices this campaign's keywords and targets to their "
                 f"role's price; a +{t0:g}% boost would pay up to {1 + t0 / 100:g}x that at the top of search."
                 + (' The campaign name carries a placement experiment: it ends here, and its targets are priced like any other.'
                    if placement_review.EXPERIMENT_MARKER.search(c.get('name') or '') else '')
                 + (' The campaign is paused: set now, so turning it back on starts at the policy.' if (c.get('state') or '').upper() == 'PAUSED' else '')),
            how='MAP update sp_campaigns: budget unchanged + complete dynamicBidding, top of search 0% (send every existing placement)')

    # down-only bidding (Kim, 2026-10-26, decision 140): every live Sponsored Products campaign on up-and-down bidding moves
    # to down only, its placement and audience adjustments resent as live (placement_review.strategy_rows). An audience
    # copy, and a campaign not shown to advertise this product alone, wait for a person
    for row in placement_review.strategy_rows(camps, asin, plc, kind, placement_review.read_inputs(run, asin)
                                              if os.path.exists(os.path.join(run, 'placement_inputs.json')) else None):
        add(**row)

    for row in bh_rows:
        add(**row)

    # funnel negatives: each invest search gets one owner; skip close variants inside exact SKCs (they would block the SKC).
    # The consumer owner never negates its search in a business campaign (a different shopper: business accounts only) or
    # in an audience copy (a different lane)
    owners = defaultdict(set)
    for p in plan:
        if p['family'] == 'SKC' and p['action'].startswith(('Invest', 'Prove')):
            owners[norm(p['keyword'])].add(p['campaign_id'])
    for t, c in reuse.items():
        owners[t].add(str(c.get('campaignId')))
    skipped = []
    # every invest search not deferred, with the campaigns that own it (none yet for a new exact campaign)
    funnel_negatives({t: owners.get(t, set()) for t in rank_terms if t not in deferred_rank_terms}, st_rows, 'consumer',
                     kind, add, skipped,
                     why='This ad group paid for the search in the last 90 days; the exact campaign owns it from now on.',
                     exact_marker='Exact SKC',
                     exact_why='inside another exact SKC; Amazon close-variant matching makes this risky',
                     variant_why=lambda own: f'close variant of the exact SKC\'s own keyword "{own}": a negative here would switch that SKC off')

    # funnel negatives inside the business kind (business.funnel_negatives; design 4c), after the consumer ones
    ctx.B2B_WHY = B2B_WHY
    business.funnel_negatives(ctx, add, skipped)

    # ---- 3a. blacklist rescue (Kim, 2026-10-21): no Invest or Prove-first search may sit on the product's Scale Insights
    #          blacklist, as itself, a close variant or a phrase inside it (scripts/blacklist_rescue.py). Checked when the
    #          run folder holds the product's lists (si_blacklist.json); a person approves the edit (Scale Insights setup).
    #          The business invests count too (design 4h): the blacklist reaches the B2B ad groups as it does the consumer ones
    bl_path = os.path.join(run, 'si_blacklist.json')
    blacklist_out = dict(checked=False, note='no si_blacklist.json in the run folder (references/scale-insights-playbook.md, '
                                             '"Blacklist rescue")')
    if os.path.exists(bl_path):
        bl_lists = blacklist_rescue.load_lists(bl_path)
        protected = blacklist_rescue.invested_searches(cfg, rank_terms, cfg.get('business_invest_log'), business_rank_terms, sizes)
        bl = blacklist_rescue.rescue(protected, bl_lists,
                                     (shared.get('scale_insights') or {}).get('blacklist_keep') or [])
        bl_row = blacklist_rescue.plan_row(asin, bl, bl_lists.get('_read'))
        if bl_row:
            add(**bl_row)
        blacklist_out = dict(checked=True, exact_remove=len(bl['exact_remove']), phrase_remove=len(bl['phrase_remove']),
                             whitelist_add=len(bl['whitelist_add']))

    # ---- 3b. Sponsored Brands video: one exact keyword per invest search in the product's "Highest Converting Search
    #          Terms" video series, at the search's invest bid, Amazon's bid optimisation off. Replaces the SKC audit's
    #          SB video build. Older SB copies of an invest search are paused, so one campaign owns it in SB too.
    sbc = dict(shared.get('sb_video') or {})
    sbc.update(cfg.get('sb_video') or {})
    sb_out = dict(status='not pulled: no sb_campaigns*.json in the run folder')
    sb_priced = set()   # the SB keyword, target and theme ids the planner priced or handed to an owner this run (the ledger reads it)

    # what a Sponsored Brands click converts at against a Sponsored Products click on the same search (config
    # sb_video.sb_cvr_ratio, 0.78: Kim, 2026-10-25, decision 135, "optimise sponsored brands bids at its own cvr"). It
    # replaced sb_cpc_ratio (1.2, what a video click cost), which priced SB above SP although SB converts worse
    ratio = float(sbc.get('sb_cvr_ratio', sbc.get('sb_cpc_ratio', 1.0)))
    # an invest (rank) search's SB keyword keeps bidding to be visible: its Sponsored Products invest bid x sb_rank_ratio
    # (1.0, Kim's rank push, decision 135), not the conversion ratio the other SB keywords take
    rank_ratio = float(sbc.get('sb_rank_ratio', ratio))
    sb_min = float(sbc.get('min_bid') or 0)   # Amazon's lowest SB keyword bid ($0.25): no SB bid is planned under it

    def invest_bid(t):
        # The search's Sponsored Products invest bid x sb_rank_ratio. Amazon gives no SB suggested bids through MAP.
        r = terms[t]
        lo, med, hi = rank_suggestions.get(t, (None, None, None))
        return round(max(sb_min, invest_bid_unrounded(med, hi, r['be_cpc']) * rank_ratio), 2)

    def sb_invest_why(t):
        if t in fallback_sources:
            source, note = fallback_sources[t]
            basis = ('no Amazon suggestion; ' + note)
            if source != 'none':
                basis += ', or breakeven if higher'
                if rank_suggestions.get(t, (None, None, None))[2]:
                    basis += ', capped at that source\'s high'
        else:
            basis = "Amazon's suggested median, or breakeven if higher, never above the high"
        return (f'Bid: its Sponsored Products invest bid ({basis}) x {rank_ratio:g}: a rank search keeps bidding to be visible '
                f'in Sponsored Brands too, while its other SB keywords bid at {ratio:g}, what a Sponsored Brands click converts '
                'at against a Sponsored Products click (decision 135). Amazon gives no Sponsored Brands suggested bids.')

    sb_rank_ids = set()   # the SB rank campaigns, which the leak check leaves out (decision 175)
    if sb['campaigns'] and sbc.get('enabled', True):
        # audience copies and business (B2B) video campaigns are a different shopper: never the AI's series, never paused
        # as an older copy of an invest search (the SB inventory read has no siteRestrictions, so the name marker decides)
        excluded = lambda n: kind(n) != 'consumer'
        live = {i: c for i, c in sb['campaigns'].items() if (c.get('state') or '').upper() != 'ARCHIVED'}
        ai_ids = {str(x) for x in sbc.get('campaigns') or []}
        hcst = [c for c in live.values() if 'Highest Converting Search Terms' in (c.get('name') or '') and not excluded(c.get('name'))]
        fam_re = re.compile(r'^(.*Highest Converting Search Terms\s*-\s*)Exact(\s*-\s*)(\d+)\s*$')
        exact_n = [(int(m.group(3)), m) for m in (fam_re.match(c.get('name') or '') for c in hcst) if m]
        if exact_n:
            n_max, m = max(exact_n, key=lambda x: x[0])
            name_for = lambda n, m=m: f"{m.group(1)}Exact{m.group(2)}{n}"
        else:
            n_max = 0
            name_for = lambda n: f"{prefix}Videos - Highest Converting Search Terms - Exact - {n}"
        budgets = [c.get('budget') for c in hcst if c.get('budget')]
        sb_budget = sbc.get('budget') or (Counter(budgets).most_common(1)[0][0] if budgets else sbc.get('default_budget', 10))
        asset = sbc.get('video_asset_id')
        chunk = int(sbc.get('keywords_per_campaign', 8))
        video_ids = sorted(i for i, c in live.items() if 'Video' in (c.get('name') or '') and not excluded(c.get('name')))
        # every SB campaign's keywords are read, video and collection: the older ones are priced too, cut only (decision 135:
        # "price the older SB campaigns that woke up the same way"), and since decision 155 (2026-10-27) the audience and B2B
        # copies too (capped, never raised) and the product and category targets (sb_video.targets)
        sb_ids = sorted(live)
        want_targets = bool(sbc.get('targets'))
        want_themes = bool(sbc.get('themes'))
        if (not sb['pulled'] or (want_targets and not sb.get('targets_pulled', True))
                or (want_themes and not sb.get('themes_pulled', True))):
            groups = [','.join(sb_ids[i:i + 20]) for i in range(0, len(sb_ids), 20)]
            write_json(os.path.join(run, 'need_sb_keywords.json'),
                       dict(asin=asin, campaign_id_groups=groups,
                            keywords_read=sb['pulled'], targets_read=sb.get('targets_pulled', True) or not want_targets,
                            themes_read=sb.get('themes_pulled', True) or not want_themes,
                            how='MAP list_resources sb_keywords, filters {campaign_id: <one group>, max_results: 500}; every page '
                                '(next_token) of every group saved as sb_keywords_p1.json, sb_keywords_p2.json, ...'
                                + ('; and the same for sb_targets (filters {campaign_id: <one group>, max_results: 500}), saved as '
                                   'sb_targets_p1.json, sb_targets_p2.json, ...' if want_targets else '')
                                + ('; and sb_themes (filters {campaign_id: <one group>, max_results: 500}), saved as '
                                   'sb_themes_p1.json, ...' if want_themes else '') + '; then rerun.'), indent=1)
        exact_rows = lambda t: [k for k in sb['cover'].get(t, []) if (k.get('matchType') or '').upper() == 'EXACT'
                                and (k.get('state') or '').upper() == 'ENABLED'
                                and (live.get(str(k.get('campaignId'))) or {}).get('state', '').upper() == 'ENABLED']
        owned = {t for t in rank_terms if any(str(k.get('campaignId')) in ai_ids for k in exact_rows(t))}
        # the SB rank campaigns: the AI's video series and any SB campaign holding an invest search's live exact keyword
        sb_rank_ids = set(ai_ids) | {str(k.get('campaignId')) for t in set(rank_terms) | {norm(x) for x in cfg.get('invest_log') or {}}
                                     for k in exact_rows(t)}
        todo = sorted([t for t in rank_terms if sb['pulled'] and t not in owned],
                      key=lambda t: (terms[t]['sub_role'] != 'Invest', -(terms[t]['sqp_volume'] or 0), t))
        for i in range(0, len(todo), chunk):
            cname = name_for(n_max + 1 + i // chunk)
            for t in todo[i:i + chunk]:
                r = terms[t]
                lo, med, hi = rank_suggestions.get(t, (None, None, None))
                add(step=91, type='New SB video campaign', keyword=t, match='exact', role=r['sub_role'], campaign=cname, new=invest_bid(t),
                    budget=sb_budget, sug_low=lo, sug_median=med, sug_high=hi, video_asset=asset, evidence=evidence_text(r),
                    why="Invest search with no exact keyword in the AI's Sponsored Brands video campaigns. " + sb_invest_why(t),
                    **fallback_field(t),
                    how=(f"MAP create, in order: sb_campaigns (${sb_budget}/day, PAGE_VISIT, CPC, MANUAL, bidOptimization false), sb_ad_groups, "
                         f"sb_ads (video, asset {'from the product file' if asset else 'MISSING: set sb_video.video_asset_id first'}), sb_keywords exact. "
                         f"Then set portfolio \"{sbc.get('portfolio_name', '3. Video Ads - Normal Bids')}\" in the Amazon Ads console."))
        new_sb_campaigns = sorted({x['campaign'] for x in changes if x['type'] == 'New SB video campaign'})
        if new_sb_campaigns:
            # assigning a strategy that exists is the standard setup and applies on its own; creating strategy 144 is a new
            # rule set beyond the standard AI setup, Kim's call (autonomous runs, 2026-10-22, decision 98)
            beyond = (None if sbc.get('si_strategy') else
                      'strategy 144 (Brand video exact owners) does not exist yet and would have to be created')
            add(step=94, type='Scale Insights setup', item=f"{len(new_sb_campaigns)} new SB video campaign(s): assign once Scale Insights syncs them",
                current='Not in Scale Insights yet (no dayparting, no strategy)',
                new=f"Strategy {sbc.get('si_strategy') or '144 (Brand video exact owners: no blacklist, no negative rules, rule 203; create it once)'}",
                why='Exact owners must not get the blacklist: Amazon applies close variants to negatives and would switch them off.',
                how='Scale Insights web app, Brand video keywords page (references/scale-insights-playbook.md)',
                **({'si_beyond_standard': beyond} if beyond else {}))
        sb_handled = set()   # SB keyword ids given a copy row below: the pricing loop leaves them alone
        for t in rank_terms:
            if t not in owned and t not in todo:
                continue
            for k in exact_rows(t):
                cid = str(k.get('campaignId'))
                if cid in ai_ids or excluded((live.get(cid) or {}).get('name')):
                    continue
                sb_handled.add(str(k.get('keywordId')))
                # paused only once the AI's own video holds the search (it is `owned`, from the run after the video is made):
                # while the video is new, held or still in Amazon's moderation, the copy keeps serving at the holding bid
                # below, so the search never goes dark (2026-10-26: the prayer cards run paused 15 copies of searches whose
                # videos were held, and the 150-card run 19 copies of searches whose new videos were still in moderation)
                if t in owned:
                    add(step=93, type='SB pause keyword', keyword=t, match='exact', role=terms[t]['sub_role'],
                        campaign=(live.get(cid) or {}).get('name'), current=k.get('bid'), new=None,
                        keyword_id=str(k.get('keywordId')), campaign_id=cid, ad_group_id=str(k.get('adGroupId')),
                        why="The AI's own Sponsored Brands video campaign owns this search; this older copy (Amazon's bid "
                            "optimisation on) is paused. Its history stays.",
                        how='MAP update sb_keywords: state PAUSED (keywordId + adGroupId)')
                # consolidate before adding (decision 135): while the new video waits to serve, its older copy drops to a
                # low holding bid the same day, so the two don't both spend on the search
                cur = num(k.get('bid')) if k.get('bid') not in (None, '') else None
                if t not in todo or copy_hold_cvr is None or not cur:
                    continue
                hb = round(max(sb_min, PROFIT * copy_hold_cvr), 2)
                if round(cur, 2) <= hb:
                    continue
                add(step=92, type='SB bid change', keyword=t, match='exact', role=terms[t]['sub_role'], campaign=(live.get(cid) or {}).get('name'),
                    current=round(cur, 2), new=hb, change=round(hb / cur - 1, 3), keyword_id=str(k.get('keywordId')), campaign_id=cid,
                    ad_group_id=str(k.get('adGroupId')), copy_hold=True,
                    why=(f"Copy of a search the AI's new Sponsored Brands video takes over this run: held at a low bid (${hb:.2f}) "
                         'from today so the two don\'t both spend on it, and paused once the new video serves (decision 135).'),
                    how='MAP update sb_keywords: bid (keywordId + adGroupId)')
        # weekly pricing of the SB keywords by the same roles as Sponsored Products, on Sponsored Brands' own conversion: its
        # own 90-day clicks and orders, shrunk toward its search's conversion x sb_cvr_ratio (decision 135). The AI's own
        # campaigns are priced both ways; an older consumer campaign's keywords are cut only, never raised
        n_sb_bids = n_sb_legacy = n_sb_paused = n_sb_copies = 0
        sb_paused_on = bool(sbc.get('paused'))
        # the suggested mid on the AI's own live consumer SB keywords (decision 177): the same states as Sponsored Products
        # on their own SB clicks and orders, the owning copy only (sb_mid_of: keyword id -> its mid row)
        sb_mid_of, sb_cands = {}, []
        for k in (sb['keywords'] if mid_cfg and mid_cfg['sponsored_brands'] else []):
            kid, cid = str(k.get('keywordId')), str(k.get('campaignId'))
            camp_sb = live.get(cid) or {}
            if (cid not in ai_ids or kind(camp_sb.get('name')) != 'consumer' or kid in sb_handled
                    or (k.get('state') or '').upper() != 'ENABLED' or (camp_sb.get('state') or '').upper() != 'ENABLED'):
                continue
            t, mt = norm(k.get('keywordText')), (k.get('matchType') or '').lower()
            r = terms.get(t)
            if brand(t) or wrong_size(t, sizes):
                continue
            pf = sb['perf'].get(kid) or {}
            clk, od = num(pf.get('clicks')), num(pf.get('purchases') or pf.get('orders'))
            # the AI's own SB keywords take their search's role, any match type (Test without a record), as the loop prices them
            role = (r or {}).get('role') or 'Test'
            ladder = max(od, (r or {}).get('sqp_our_purchases') or 0, (r or {}).get('ad_orders') or 0)
            st = mid_bid.state(role, clk, od, ladder, (r or {}).get('index'), mid_cfg, ASIN_AD_CVR)
            if st in mid_bid.MID_STATES:
                sb_cands.append((kid, t, mt, clk, od, st, num(pf.get('cost') or pf.get('spend'))))
        sb_owner = mid_bid.owners([(kid, t, mt, clk, od) for kid, t, mt, clk, od, _, _ in sb_cands])
        for kid, t, mt, clk, od, st, spend in sb_cands:
            if sb_owner.get((t, mt)) != kid:
                continue
            mid, src, words_ = mid_value(None, t, mt, (spend / clk) if clk else None, clk, tried=True)
            if mid:
                f = float(osh['top10_factor']) if t in top10 else 1.0
                sb_mid_of[kid] = dict(state=st, mid=mid, bid=round(max(sb_min, mid * rank_ratio * f), 2), source=src,
                                      priced_on=words_, factor=f, sb_rank_ratio=rank_ratio, clicks90=int(clk), orders90=int(od),
                                      spend90=round(spend, 2), keyword=t, match=mt)
        for k in sb['keywords']:
            kid, cid = str(k.get('keywordId')), str(k.get('campaignId'))
            ai = cid in ai_ids
            camp_sb = live.get(cid) or {}
            k_state, c_state = (k.get('state') or '').upper(), (camp_sb.get('state') or '').upper()
            if kid in sb_handled:
                sb_priced.add(kid)
            if kid in sb_handled or k_state not in ('ENABLED', 'PAUSED') or c_state not in ('ENABLED', 'PAUSED'):
                continue
            # a paused keyword, or one of a paused campaign, is priced cut only and stays paused (decision 155, sb_video.paused)
            paused_sb = k_state == 'PAUSED' or c_state == 'PAUSED'
            if paused_sb and not sb_paused_on:
                continue
            sb_priced.add(kid)
            t = norm(k.get('keywordText'))
            r = terms.get(t)
            mt = (k.get('matchType') or '').lower()
            pf = sb['perf'].get(kid) or {}
            clk, od = num(pf.get('clicks')), num(pf.get('purchases') or pf.get('orders'))
            cur = num(k.get('bid')) if k.get('bid') not in (None, '') else None
            ck = kind(camp_sb.get('name'))
            if not ai and ck != 'consumer':
                # an audience or B2B copy (decision 155): a different shopper, so never the AI's series and never paused as an
                # older copy; its bid is capped at its breakeven x the non-rank share and never raised, like the SP copies
                base_c = B2B_CVR if ck == 'business' else ASIN_AD_CVR
                be = PROFIT * (od + PRIOR * base_c * ratio) / (clk + PRIOR)
                new = round(max(sb_min, be * nr_for(t)), 2)
                if cur is None or round(new, 2) >= round(cur, 2):
                    continue
                n_sb_bids += 1
                n_sb_copies += 1
                n_sb_paused += paused_sb
                add(step=92, type='SB bid change', keyword=t, match=mt, role='Business cap' if ck == 'business' else 'Audience cap',
                    campaign=camp_sb.get('name'), current=round(cur, 2), new=new, change=round(new / cur - 1, 3), clicks90=int(clk),
                    orders90=int(od), spend90=round(num(pf.get('cost') or pf.get('spend')), 2), keyword_id=kid, campaign_id=cid,
                    ad_group_id=str(k.get('adGroupId')), **(dict(paused=True) if paused_sb else {}),
                    **(dict(owner_kind='business') if ck == 'business' else {}),
                    why=(("Amazon Business (B2B) " if ck == 'business' else 'Audience (AMC, low-bid) ')
                         + f"Sponsored Brands copy: capped at {nr_words} on its own clicks and orders (90 days), shrunk toward "
                         + ("the B2B campaigns' conversion" if ck == 'business' else "the product's ad conversion")
                         + f" x {ratio:g}; never raised (decision 155)."
                         + (" Paused: priced now, cut only; it stays paused." if paused_sb else '')),
                    how='MAP update sb_keywords: bid (keywordId + adGroupId)' + (' (it stays paused)' if paused_sb else ''))
                continue
            prior = (((r or {}).get('cvr_est') if mt == 'exact' else None) or ASIN_AD_CVR) * ratio
            be = PROFIT * (od + PRIOR * prior) / (clk + PRIOR)
            # decision 162: the search's own SQP price (exact), or the searches it served (phrase, broad), x the SB ratio
            sv_sb = served_price(kid) if mt != 'exact' else None
            if SQP_PRICE and mt == 'exact' and r:
                be = PROFIT * r['cvr_price'] * ratio
            elif sv_sb:
                be = PROFIT * sv_sb[0] * ratio
            role = 'Negate' if wrong_size(t, sizes) else (r or {}).get('role') or 'Test'
            if paused_sb and role in ('Negate', 'Rank'):
                continue   # a paused copy stays paused; an invest search's own bid is set on its live keyword
            if not ai and role != 'Negate' and mt != 'exact':
                role = 'Discovery'
            if not ai and role in ('Negate', 'Rank'):
                continue   # an older copy's irrelevant search is the negative audit's; its invest copies are handled above
            if role == 'Negate':
                add(step=93, type='SB pause keyword', keyword=t, match=(k.get('matchType') or '').lower(), role='Negate', campaign=(live.get(str(k.get('campaignId'))) or {}).get('name'),
                    current=cur, new=None, keyword_id=str(k.get('keywordId')), campaign_id=str(k.get('campaignId')), ad_group_id=str(k.get('adGroupId')),
                    why='Irrelevant search for this product.', how='MAP update sb_keywords: state PAUSED')
                continue
            if (leak_pause and org_on and role in ('Hold', 'Defend', 'Test', 'Discovery') and cid not in sb_rank_ids and not paused_sb
                    and ck == 'consumer' and clk >= osh['leak_pause_clicks'] and not od and cur
                    and (sb_mid_of.get(kid) or {}).get('state') not in ('testing', 'extended')):
                # the leak check (decision 175): an ordinary SB keyword with 15+ clicks and no order pauses while the
                # product's ordinary campaigns lose money; a rank campaign's keywords never do
                add(step=93, type='SB pause keyword', keyword=t, match=mt, role=role, campaign=camp_sb.get('name'), current=cur,
                    new=None, clicks90=int(clk), orders90=0, spend90=round(num(pf.get('cost') or pf.get('spend')), 2),
                    keyword_id=kid, campaign_id=cid, ad_group_id=str(k.get('adGroupId')),
                    why=(f"Leak check (decision 175): {int(clk)} clicks and no orders in 90 days while the product's ordinary "
                         f"campaigns lost money over the last {osh['leak_days']} settled days."),
                    how='MAP update sb_keywords: state PAUSED')
                continue
            if role == 'Rank':
                new, sub = invest_bid(t), r['sub_role']
            elif role in ('Hold', 'Defend'):
                new, sub = round(be * nr_for(t), 2), 'Hold'
            elif role == 'Trim':
                new, sub = round(max(th['trim_min_bid'], th['trim_factor'] * be), 2), 'Trim'
            elif role == 'Discovery':
                # decision 162: priced on the searches it served, it drops the product-average cap
                new, sub = round((be if sv_sb else min(be, PROFIT * ASIN_AD_CVR * ratio)) * nr_for(t), 2), 'Discovery'
            else:
                mk = (r or {}).get('market_cvr') or th['test_default_market_cvr']
                new, sub = test_bid(PROFIT * mk * ratio, be), 'Test'
            sb_mid = sb_mid_of.get(kid) if role in ('Hold', 'Test') and ai and not paused_sb else None
            if sb_mid:
                # the suggested mid (decision 177): its search's Sponsored Products mid x sb_rank_ratio, as an invest
                # search's SB bid is priced (Amazon gives no Sponsored Brands suggestions)
                new = sb_mid['bid']
            new = round(max(sb_min, new), 2)
            if cur is None or abs(new - cur) < 0.01 or (brand(t) and new > cur):
                continue   # a brand search's SB keyword is cut only (organic only, section 1c')
            if (not ai or paused_sb or (never_raise and clk == 0 and role != 'Rank')) and new > cur:
                continue   # an older or paused campaign is cut only; a keyword with no clicks of its own is never raised (decision 135)
            n_sb_bids += 1
            n_sb_legacy += not ai
            n_sb_paused += paused_sb
            sb_mid_extra = dict(mid_bid=dict(sb_mid, bid=new)) if sb_mid else {}
            add(step=92, type='SB bid change', keyword=t, match=(k.get('matchType') or '').lower(), role=sub,
                campaign=(live.get(str(k.get('campaignId'))) or {}).get('name'), current=round(cur, 2), new=new,
                change=round(new / cur - 1, 3) if cur else None, clicks90=int(clk), orders90=int(od), spend90=round(num(pf.get('cost') or pf.get('spend')), 2),
                keyword_id=str(k.get('keywordId')), campaign_id=str(k.get('campaignId')), ad_group_id=str(k.get('adGroupId')),
                why=('Invest search: ' + sb_invest_why(t) if role == 'Rank' else
                     ('' if ai else "Older Sponsored Brands campaign (not the AI's video series): cut only. ")
                     + f'{sub}: priced like Sponsored Products, from its own Sponsored Brands clicks and orders (90 days), '
                       f"shrunk toward its search's conversion x {ratio:g}, what a Sponsored Brands click converts at against "
                       'a Sponsored Products click (decision 135).'),
                **(fallback_field(t) if role == 'Rank' else {}), **(dict(paused=True) if paused_sb else {}), **sb_mid_extra,
                how='MAP update sb_keywords: bid (keywordId + adGroupId)' + (' (it stays paused)' if paused_sb else ''))
            if sb_mid:
                changes[-1]['why'] = (f"{sub} keyword {mid_bid.words(sb_mid['state'], mid_cfg, ASIN_AD_CVR)}: it bids its search's suggested "
                                      f"mid x {rank_ratio:g} ({sb_mid['priced_on']}), not its breakeven click (decision 177)."
                                      + (f" The product ranks top 10 for it, so {sb_mid['factor']:.0%} of that." if sb_mid['factor'] != 1 else ''))
            if paused_sb:
                changes[-1]['why'] += " Paused: priced now, cut only, so turning it back on can't bring back an old bid; it stays paused (decision 155)."
        # Sponsored Brands product and category targets (decision 155, sb_video.targets): priced on their own Sponsored
        # Brands clicks and orders, shrunk toward the product's ad conversion x the SB ratio (B2B: the B2B pool), at the
        # non-rank share of breakeven; cut only, never raised (a target is never an invest search's owner)
        n_sb_targets = 0
        for tg in (sb.get('targets') or [] if sbc.get('targets') else []):
            tid, cid = str(tg.get('targetId')), str(tg.get('campaignId'))
            camp_sb = live.get(cid) or {}
            t_state, c_state = (tg.get('state') or '').upper(), (camp_sb.get('state') or '').upper()
            if t_state not in ('ENABLED', 'PAUSED') or c_state not in ('ENABLED', 'PAUSED'):
                continue
            paused_sb = t_state == 'PAUSED' or c_state == 'PAUSED'
            if paused_sb and not sb_paused_on:
                continue
            cur = num(tg.get('bid')) if tg.get('bid') not in (None, '') else None
            if not cur:
                continue
            sb_priced.add(tid)
            ck = kind(camp_sb.get('name'))
            pf = sb['perf'].get(tid) or {}
            clk, od = num(pf.get('clicks')), num(pf.get('purchases') or pf.get('orders'))
            base_c = B2B_CVR if ck == 'business' else ASIN_AD_CVR
            be = PROFIT * (od + PRIOR * base_c * ratio) / (clk + PRIOR)
            new = round(max(sb_min, be * nr), 2)
            if round(new, 2) >= round(cur, 2):
                continue
            text = ', '.join(str(e.get('value') or e.get('type') or '') for e in (tg.get('resolvedExpressions') or tg.get('expressions') or [])
                             if isinstance(e, dict)) or tid
            n_sb_bids += 1
            n_sb_targets += 1
            n_sb_paused += paused_sb
            add(step=92, type='SB bid change', keyword=text, match='target', role='Target cap', campaign=camp_sb.get('name'),
                current=round(cur, 2), new=new, change=round(new / cur - 1, 3), clicks90=int(clk), orders90=int(od),
                spend90=round(num(pf.get('cost') or pf.get('spend')), 2), target_id=tid, campaign_id=cid,
                ad_group_id=str(tg.get('adGroupId')), **(dict(paused=True) if paused_sb else {}),
                **(dict(owner_kind='business') if ck == 'business' else {}),
                why=(f"Sponsored Brands product or category target: priced at {nr_words} on its own clicks and orders (90 days), "
                     f"shrunk toward {'the B2B campaigns' if ck == 'business' else 'the product'}'s ad conversion x {ratio:g}; "
                     'cut only, never raised (decision 155).' + (' Paused: it stays paused.' if paused_sb else '')),
                how='MAP update sb_targets: bid (targetId + adGroupId)' + (' (it stays paused)' if paused_sb else ''))
        # Sponsored Brands theme targets (decision 156, sb_video.themes): priced like the SB product targets above, on their own
        # 90-day clicks and orders shrunk toward the product's ad conversion x the SB ratio, at the non-rank share of
        # breakeven; cut only, never raised (a theme is a group of searches Amazon picks, never an invest search's owner)
        n_sb_themes = 0
        for th_ in (sb.get('themes') or [] if sbc.get('themes') else []):
            hid, cid = str(th_.get('themeId')), str(th_.get('campaignId'))
            camp_sb = live.get(cid) or {}
            t_state, c_state = (th_.get('state') or '').upper(), (camp_sb.get('state') or '').upper()
            if t_state not in ('ENABLED', 'PAUSED') or c_state not in ('ENABLED', 'PAUSED'):
                continue
            paused_sb = t_state == 'PAUSED' or c_state == 'PAUSED'
            if paused_sb and not sb_paused_on:
                continue
            cur = num(th_.get('bid')) if th_.get('bid') not in (None, '') else None
            if not cur:
                continue
            sb_priced.add(hid)
            ck = kind(camp_sb.get('name'))
            pf = sb['perf'].get(hid) or {}
            clk, od = num(pf.get('clicks')), num(pf.get('purchases') or pf.get('orders'))
            base_c = B2B_CVR if ck == 'business' else ASIN_AD_CVR
            be = PROFIT * (od + PRIOR * base_c * ratio) / (clk + PRIOR)
            new = round(max(sb_min, be * nr), 2)
            if round(new, 2) >= round(cur, 2):
                continue
            text = {'KEYWORDS_RELATED_TO_YOUR_BRAND': 'keywords related to your brand',
                    'KEYWORDS_RELATED_TO_YOUR_LANDING_PAGES': 'keywords related to your landing pages'}.get(
                        str(th_.get('themeType') or '').upper(), str(th_.get('themeType') or hid).lower())
            n_sb_bids += 1
            n_sb_themes += 1
            n_sb_paused += paused_sb
            add(step=92, type='SB bid change', keyword=text, match='theme', role='Theme cap', campaign=camp_sb.get('name'),
                current=round(cur, 2), new=new, change=round(new / cur - 1, 3), clicks90=int(clk), orders90=int(od),
                spend90=round(num(pf.get('cost') or pf.get('spend')), 2), theme_id=hid, campaign_id=cid,
                ad_group_id=str(th_.get('adGroupId')), **(dict(paused=True) if paused_sb else {}),
                **(dict(owner_kind='business') if ck == 'business' else {}),
                why=(f"Sponsored Brands theme target ({text}): Amazon picks the searches, so it is priced at {nr_words} on its "
                     f"own clicks and orders (90 days), shrunk toward the product's ad conversion x {ratio:g}; cut only, never "
                     'raised (decision 156).' + (' Paused: it stays paused.' if paused_sb else '')),
                how='MAP update sb_themes: bid (themeId + adGroupId)' + (' (it stays paused)' if paused_sb else ''))
        # Amazon's bid optimisation on an older SB campaign raises and lowers the bid on its own, so the price set above is not
        # what it pays: switched off (decision 155, sb_video.bid_optimisation_off), on its own. With it off Amazon applies the
        # campaign's saved placement modifiers, so every positive one goes to 0% in the same write (the placement policy)
        n_sb_opt = 0
        for cid, c in sorted(live.items()):
            bidding = c.get('bidding') or {}
            if (not sbc.get('bid_optimisation_off') or cid in ai_ids or not bidding.get('bidOptimization')
                    or (c.get('state') or '').upper() not in ('ENABLED', 'PAUSED')):
                continue
            placements = [dict(p, percentage=min(0, int(num(p.get('percentage'))))) for p in bidding.get('bidAdjustmentsByPlacement') or []
                          if isinstance(p, dict) and p.get('placement')]
            n_sb_opt += 1
            add(step=92, type='SB bid optimisation', keyword=None, role='Bid optimisation off', campaign=c.get('name'),
                current='on', new='off', campaign_id=cid, placements=placements, campaign_state=(c.get('state') or '').upper(),
                why=("Amazon's bid optimisation is on in this older Sponsored Brands campaign, so Amazon moves its bids up and down "
                     'and the AI\'s price is not what it pays: switched off (decision 155). '
                     + ('Its positive placement modifiers go to 0% in the same write: with optimisation off Amazon applies '
                        'them. ' if any(num(p.get('percentage')) > 0 for p in bidding.get('bidAdjustmentsByPlacement') or [] if isinstance(p, dict)) else '')
                     + ('The campaign is paused: it stays paused.' if (c.get('state') or '').upper() == 'PAUSED' else '')).strip(),
                how='MAP update sb_campaigns: bidding {bidOptimization: false, bidAdjustmentsByPlacement: every positive one at 0}')
        legacy = [c for c in live.values() if 'Video' in (c.get('name') or '') and str(c.get('campaignId')) not in ai_ids
                  and (c.get('state') or '').upper() == 'ENABLED']
        sb_out = dict(status=('ok' if sb['pulled'] else f'keywords of {len(video_ids)} video campaigns not read yet: see need_sb_keywords.json'),
                      keywords_read=len(sb['keywords']), video_campaigns=len(video_ids),
                      campaigns_read=len(live), ai_campaigns=len(ai_ids), next_exact_n=n_max + 1, budget=sb_budget, video_asset=bool(asset),
                      new_campaigns=len(new_sb_campaigns), new_keywords=len(todo), bid_changes=n_sb_bids,
                      legacy_bid_cuts=n_sb_legacy, sb_cvr_ratio=ratio, sb_rank_ratio=rank_ratio, campaigns_to_read=len(sb_ids),
                      pauses=sum(1 for x in changes if x['type'] == 'SB pause keyword'),
                      legacy_video_campaigns=len(legacy), paused_bid_cuts=n_sb_paused, copy_caps=n_sb_copies,
                      targets_read=len(sb.get('targets') or []), target_cuts=n_sb_targets, bid_optimisation_off=n_sb_opt,
                      themes_read=len(sb.get('themes') or []), theme_cuts=n_sb_themes,
                      legacy_bid_optimisation_on=sum(1 for c in legacy if (c.get('bidding') or {}).get('bidOptimization')))

    # stop-loss reviews (rulebook section 4; Kim, 2026-10-26, decision 142). An invest search is judged on what it is for,
    # gains we don't pay for: organic rank (Rank Radar) and organic purchases (SQP purchases less every ad order). SQP
    # impression share counts the impressions we buy, so it is no longer a gain. Ranking takes 10 to 12 months, so an
    # evergreen search is judged at checkpoints (thresholds.stop_loss_months: months 3, 6, 9 and 12 of investing), once each,
    # against its reading at the last checkpoint it passed (the invest log's checkpoint_*, written by log_invest.py), else
    # its start. A seasonal rank build keeps its weeks (season block stop_loss_weeks, 2 and 4), every run from the first,
    # against its start. No gain on either = step-down; neither readable = held for a person (a 'Stop-loss review').
    # A harvest invests in nothing, so has none.
    today = dt.date.fromisoformat(today_iso) if today_iso else dt.date.today()
    radar = load_radar(run)
    stop_rows = []
    stop_weeks = (season_now or {}).get('stop_loss_weeks') or shared['thresholds']['stop_loss_weeks']   # the business stop-loss's
    stop_months = None if (season_now or {}).get('stop_loss_weeks') else shared['thresholds']['stop_loss_months']
    checks_due = {} if (season_now or {}).get('harvest') else dict(rank)  # manual overrides from rank_check.json win
    for t, log in ({} if (season_now or {}).get('harvest') else (cfg.get('invest_log') or {})).items():
        t = norm(t)
        if t in checks_due or not log.get('since'):
            continue
        series = radar.get(t, [])
        last = series[-1][0] if series else None
        rank_now = median_rank(series, (dt.date.fromisoformat(last) - dt.timedelta(days=6)).isoformat(), last) if last else None
        tr = terms.get(t, {})
        checks_due[t] = dict(since=log['since'], rank_then=log.get('rank_then'), rank_now=rank_now,
                             organic_then=log.get('organic_then'), organic_now=tr.get('organic_purchases'),
                             **{k: log.get(k) for k in ('checkpoint', 'checkpoint_rank', 'checkpoint_organic')})
    for t, rc in checks_due.items():
        try:
            age = (today - dt.date.fromisoformat(rc.get('since'))).days
        except (TypeError, ValueError):
            continue
        if stop_months:
            passed = [m for m in stop_months if age >= checkpoint_days(m)]
            last_cp = rc.get('checkpoint') or 0
            if not passed or last_cp >= passed[-1]:
                continue
            checkpoint = passed[-1]
            base_label = f'the month {last_cp} checkpoint' if last_cp else 'its start'
            rank_base, organic_base = ((rc.get('checkpoint_rank'), rc.get('checkpoint_organic')) if last_cp
                                       else (rc.get('rank_then'), rc.get('organic_then')))
            when = f'invested {age} days (the month {checkpoint} checkpoint)'
        else:
            if age < 7 * stop_weeks[0]:
                continue
            checkpoint, base_label = None, 'its start'
            rank_base, organic_base = rc.get('rank_then'), rc.get('organic_then')
            when = f'invested {age} days ({age // 7} weeks)'
        gains, readable = [], 0
        if rank_base is not None and rc.get('rank_now') is not None:
            readable += 1
            if rc['rank_now'] < rank_base:
                gains.append(f"organic rank {rank_base:.0f} -> {rc['rank_now']:.0f}")
        if organic_base is not None and rc.get('organic_now') is not None:
            readable += 1
            if rc['organic_now'] > organic_base:
                gains.append(f"organic purchases {organic_base:g} -> {rc['organic_now']:g}")
        stop_rows.append(dict(keyword=t, age_days=age, checkpoint=checkpoint, against=base_label, gains=gains, readable=readable,
                              rank_base=rank_base, organic_base=organic_base,
                              **{k: rc.get(k) for k in ('rank_then', 'rank_now', 'organic_then', 'organic_now')}))
        if gains:
            continue
        hold_budget = bud['prove_per_day']   # the rulebook's Hold budget ($5/day), the small standard one
        if not readable:
            stop_rows[-1]['step_down'] = 'review'
            add(step=8, type='Stop-loss review', keyword=t, role=terms.get(t, {}).get('sub_role') or 'Invest', current=None, new=None,
                why=f"{when.capitalize()}, but neither organic rank nor organic purchases can be read against {base_label} "
                    f"(rank {rank_base} -> {rc.get('rank_now')}, organic purchases {organic_base} -> {rc.get('organic_now')}): "
                    f"no Rank Radar reading or SQP row. A person decides whether it steps down to Hold (breakeven bid, top of "
                    f"search 0%, ${hold_budget:g}/day); a Rank Radar for it lets the next checkpoint judge it.",
                how='Held (Monitor): the next run tries the step-down again once it can be written (decision 107); it is then a MAP bid + campaign update, and log_invest.py records it')
            continue
        # autonomous runs (Kim, 2026-10-22, decision 98): the planner writes the step-down itself (stop_loss.py), back
        # to Hold: the owner keyword at its breakeven, its campaign at top of search 0% and the Hold budget. Only where no
        # owner keyword is in this run's keyword report is it a person's 'Stop-loss review'
        reason = (f"{when} with no gain since {base_label} in organic rank ({rank_base} -> {rc.get('rank_now')}) or "
                  f"organic purchases ({organic_base} -> {rc.get('organic_now')})")
        done = stop_loss.step_down(changes, add, t, stop_loss.owner_row(plan, t), reason, live_budget_tos,
                                   budget_to=hold_budget,
                                   bid_to=cap_low(t) if (terms.get(t) or {}).get('over_rank_cap') else None)
        stop_rows[-1]['step_down'] = done or 'review'
        if done is None:
            add(step=8, type='Stop-loss review', keyword=t, role=terms.get(t, {}).get('sub_role') or 'Invest', current=None, new=None,
                why=f"{reason.capitalize()}. Step down to Hold (breakeven bid, top of search 0%, ${hold_budget:g}/day). No "
                    f"step-down could be written: its exact keyword in an exact campaign isn't in this run's keyword report.",
                how='Held (Monitor): the next run tries the step-down again once it can be written (decision 107); it is then a MAP bid + campaign update, and log_invest.py records it')

    # the index slip and the rank volume cap (decision 182, Kim 2026-11-04): a logged invest search whose own record now
    # says Trim (trusted index under thresholds.index_hold, 0.8, on thresholds.trim_min_clicks, 15, or more of our clicks),
    # or that is over thresholds.rank_max_monthly_searches (over_rank_cap, the role ladder), steps down at this run,
    # not at its next stop-loss checkpoint: the same step-down (owner keyword at no more than breakeven, top of search 0%,
    # the Hold budget), so log_invest.py takes it out of the invest log once it has gone out. A seasonal rank build's
    # searches keep the season's own weeks for the index slip, but one over the rank cap steps down too (decision 185,
    # Kim 2026-11-04: "Yes, cap seasonal too"; B0SAMP0010's "thanksgiving stickers" kept +50% top of search and $12/day);
    # harvest already takes every season campaign back to top of search 0%. A search the checkpoint above already stepped
    # down is left as it is
    slip_cfg = shared['thresholds'].get('slip_step_down', True)
    stepped = {r['keyword'] for r in stop_rows if r.get('step_down')}
    skip_loop = slip_cfg is False or bool(season_now and season_now['harvest'])
    for t, log in ({} if skip_loop else (cfg.get('invest_log') or {})).items():
        t = norm(t)
        tr = terms.get(t) or {}
        clicks_seen = tr.get('sqp_our_clicks') if (tr.get('index_basis') or '').startswith('SQP') else tr.get('ad_clicks')
        # decision 182 needs 15+ of our clicks (thresholds.trim_min_clicks): a Trim on fewer, a decision 177 "validated"
        # Trim (2+ orders under index 0.8 before the clicks to be trusted), keeps investing until it has them
        # (B0SAMP0001 "prayer bookmarks" stepped down on 13 clicks, 2026-11-04)
        slipped = (tr.get('role') == 'Trim' and tr.get('index') is not None and not season_now
                   and (clicks_seen or 0) >= th['trim_min_clicks'])
        if t in stepped or not (slipped or tr.get('over_rank_cap')):
            continue
        reason = (f"its index slipped to {tr['index']:.2f} (under {th['index_hold']:g}) on {int(clicks_seen or 0)} of our "
                  f"clicks: rank money goes to searches that beat the market (decision 182)" if slipped else
                  f"it has about {tr.get('monthly_searches') or 0:,.0f} searches a month, over the "
                  f"{float(tr.get('rank_cap') or cfg.get('rank_max_monthly_searches') or th.get('rank_max_monthly_searches') or 0):,.0f} rank cap: rank moved on smaller searches (decision 182)")
        done = stop_loss.step_down(changes, add, t, stop_loss.owner_row(plan, t), reason, live_budget_tos,
                                   budget_to=bud['prove_per_day'], bid_to=None if slipped else cap_low(t))
        stop_rows.append(dict(keyword=t, age_days=None, checkpoint=None, against='index slip', gains=[], readable=None,
                              slip=slipped, over_rank_cap=bool(tr.get('over_rank_cap')), index=tr.get('index'),
                              step_down=done or 'review'))
        if done is None:
            add(step=8, type='Stop-loss review', keyword=t, role=log.get('role') or 'Invest', current=None, new=None,
                why=f"{reason.capitalize()}. Step down to Hold (breakeven bid, top of search 0%, ${bud['prove_per_day']:g}/day). "
                    f"No step-down could be written: its exact keyword in an exact campaign isn't in this run's keyword report.",
                how='Held (Monitor): the next run tries the step-down again once it can be written (decision 107); it is then a MAP bid + campaign update, and log_invest.py records it')

    # business stop-loss reviews (business.stop_loss; design 4f), after the consumer ones
    ctx.today, ctx.stop_weeks = today, stop_weeks
    business.stop_loss(ctx, add, stop_rows)

    # ---- 4. harvest settings (computed per ASIN; the SI import rule bids the harvest ad group's default bid)
    harvest_suggestions, harvest_source = {t: v for t, v in sug.items() if not wrong_size(t, sizes)
                                          and not approved_phrase_reason(t, cfg.get('relevance') or {})}, 'amazon'
    if not any(v and v[1] for v in harvest_suggestions.values()) and bids_tried is not None:
        # An import gate needs a real low estimate; own CPC / breakeven cannot supply a range.
        harvest_suggestions = {t: v for t, v in bid_fallback.load_soldscope(run, load_suggested).items()
                               if t in terms and not wrong_size(t, sizes)
                               and not approved_phrase_reason(t, cfg.get('relevance') or {})
                               and all(v) and 0 < v[0] <= v[1] <= v[2]}
        harvest_source = 'soldscope'
    meds = [v[1] for v in harvest_suggestions.values() if v and v[1]]
    lows = [v[0] for v in harvest_suggestions.values() if v and v[0]]
    highs = [v[2] for v in harvest_suggestions.values() if v and v[2]]
    harvest = {}
    if meds:
        be_avg = PROFIT * ASIN_AD_CVR
        med_med = statistics.median(meds)
        cap = statistics.median(highs) if highs else med_med
        default_bid = round(min(max(med_med, be_avg), cap), 2)
        gate = statistics.median(lows) / PROFIT if lows else None
        bands = shared['harvest']['gate_bands']
        band = max([b for b in bands if gate is not None and b <= gate] or [min(bands)])
        rule = shared['scale_insights']['import_rules_by_gate'].get(f'{band:.2f}') or shared['scale_insights']['import_rules_by_gate'].get(str(band))
        hv = cfg.get('harvest') or {}
        harvest = dict(default_bid=default_bid, bid_source=harvest_source,
                       priced_on=("Amazon's suggested ranges" if harvest_source == 'amazon' else "SoldScope's exact-query estimated ranges"),
                       median_of_medians=round(med_med, 3), breakeven_click_avg=round(be_avg, 2),
                       median_high=round(cap, 2), gate=round(gate, 4) if gate else None, gate_band=band, import_rule_id=rule,
                       priced_searches=len(meds), ad_group_id=hv.get('ad_group_id'), current_default_bid=hv.get('default_bid'),
                       note=('Create an import rule for this gate band first (copy rule 21051, swap the criteria profile).' if not rule else ''))
        if hv.get('ad_group_id') and hv.get('default_bid') != default_bid:
            add(step=6, type='Harvest default bid', keyword='(harvest ad group)', role='Harvest', campaign=hv.get('campaign_id'),
                campaign_id=hv.get('campaign_id'),
                current=hv.get('default_bid'), new=default_bid, ad_group_id=hv.get('ad_group_id'),
                bid_source=harvest_source,
                why=f"Starting bid for newly harvested keywords: median of {harvest['priced_on']} (${med_med:.2f}), "
                    f'floored at the average breakeven click (${be_avg:.2f}), capped at the median suggested high (${cap:.2f}).',
                how='MAP update sp_ad_groups: defaultBid; then update data/asins/<ASIN>.json harvest.default_bid')

    # ad-group default bids (decision 155, inventory.ad_group_default_bids): a keyword or target with no bid of its own bids
    # its ad group's default, and Scale Insights' import rules add new keywords at it, so an old launch default is a live bid
    # nobody priced. Each default of the product's enabled or paused ad groups (live_ad_groups_p*.json) is priced like a
    # Discovery keyword (the B2B pool's conversion in a business campaign), cut only. The harvest ad group keeps its own
    # starting bid (above); rank campaigns and placement experiments are left as they are
    ag_counts = Counter()
    ag_priced = set()   # the ad groups whose default bid the planner priced this run (the ledger reads it)
    if inv_cfg.get('ad_group_default_bids') and not files(run, 'live_ad_groups'):
        ag_counts['not read'] = 1   # the coverage ledger names it: live_ad_groups_p*.json (references/data-pull.md)
    elif inv_cfg.get('ad_group_default_bids'):
        hv_ag = str((cfg.get('harvest') or {}).get('ad_group_id') or '')
        camp_by = {str(c.get('campaignId')): c for c in camps}
        for g in (g for p in files(run, 'live_ad_groups') for g in load_items(p)):
            agid, cid = str(g.get('adGroupId')), str(g.get('campaignId'))
            c = camp_by.get(cid)
            g_state, c_state = (g.get('state') or '').upper(), ((c or {}).get('state') or '').upper()
            if not c or g_state not in ('ENABLED', 'PAUSED') or c_state not in ('ENABLED', 'PAUSED'):
                ag_counts['not this product or not live'] += 1
                continue
            if agid == hv_ag or cid in rank_cids or in_experiment(c):
                ag_counts['harvest, rank or experiment'] += 1
                continue
            cur = num(g.get('defaultBid')) if g.get('defaultBid') not in (None, '') else None
            if not cur:
                continue
            ag_counts['read'] += 1
            ag_priced.add(agid)
            ck = kind(c.get('name'))
            priced = round(max(th['trim_min_bid'], PROFIT * (B2B_CVR if ck == 'business' else ASIN_AD_CVR) * nr), 2)
            new, t = boost_capped(cid, priced, 'Discovery')
            new = round(max(0.02, new), 2)
            if new >= round(cur, 2):
                continue
            paused_ag = 'PAUSED' in (g_state, c_state)
            ag_counts['cut'] += 1
            add(step=6, type='Ad group default bid', keyword='(ad group default)', role='Default cap', campaign=c.get('name'),
                family=family(c.get('name')), current=round(cur, 2), new=new, change=round(new / cur - 1, 3),
                campaign_id=cid, ad_group_id=agid, **(dict(paused=True) if paused_ag else {}),
                **(dict(priced_bid=priced, boost_kept=t) if t and new < priced else {}),
                **(dict(owner_kind='business') if ck == 'business' else {}),
                why=(f"The ad group's default bid: its keywords and targets with no bid of their own bid it, and Scale Insights "
                     f"adds new keywords at it. Priced like a Discovery keyword ({nr_words} on "
                     + ("the B2B campaigns' conversion" if ck == 'business' else "the product's ad conversion")
                     + '), cut only (decision 155).'
                     + (f' Its campaign keeps a {boost_words(cid)} this run, so it bids price / {1 + t / 100:g}.' if t and new < priced else '')
                     + (' Paused: it stays paused.' if paused_ag else '')),
                how='MAP update sp_ad_groups: defaultBid' + (' (it stays paused)' if paused_ag else ''))

    if plc.get('recommendations', {}).get('enabled'):
        placement_review.hold_defaults(changes, camps, plc)
        for row in plan:
            current, settings = placement_review.settings(live_by_id.get(str(row.get('campaign_id')), {}))
            row['tos_pct'] = (current or {}).get('TOP_OF_SEARCH')
    stamp_business_campaigns(changes, business_live)   # once the placements are settled: one top of search and budget per business campaign

    # ---- 4y. shared campaigns (decision 155): a row in a multi-product campaign is priced at the lowest profit among the AI
    #      products it advertises (the product file's profit_per_unit_min), and only lowered: a bid row is scaled by that
    #      profit / this product's and kept only as a cut; the placement policy and down-only bidding stay; anything else
    #      (a budget, a pause, a new keyword) is left to a person, since this product's numbers alone don't decide it
    if shared_list:
        kept_rows, dropped = [], Counter()
        for x in changes:
            cid = str(x.get('campaign_id') or '')
            if cid not in shared_list:
                kept_rows.append(x)
                continue
            low = shared_list[cid]['profit_per_unit_min']
            if not low:
                dropped['no lowest profit'] += 1
                continue
            if x['type'] in ('Bid change', 'Target bid change', 'Ad group default bid') and x.get('current') and x.get('new') is not None:
                ratio_p = min(1.0, float(low) / PROFIT)
                new = round(max(0.02, x['new'] * ratio_p), 2)
                if new >= round(x['current'], 2):
                    dropped['not a cut'] += 1
                    continue
                x.update(new=new, change=round(new / x['current'] - 1, 3), shared_campaign=True,
                         why=x.get('why', '') + (f" Shared campaign ({', '.join(shared_list[cid]['products']) or 'several AI products'}): "
                                                 f"priced at the lowest profit among them (${float(low):.2f} a unit), cut only (decision 155)."))
                kept_rows.append(x)
            elif x.get('placement_policy') or x['type'] == 'Bidding strategy':
                x['shared_campaign'] = True
                kept_rows.append(x)
            else:
                dropped[x['type']] += 1
        changes[:] = kept_rows
        shared_out['left_out'] = dict(dropped)

    # ---- 4z. the brand sweep: whatever section built it, no row may create, fund, whitelist or raise a brand search
    #          (organic only). The role pass (1c') should leave none; any found is dropped and listed in summary.brand_guard
    brand_dropped = brand_sweep(changes, brand)

    # ---- 5. re-rank cost of the invest searches
    # A deferred rank search (an existing investment, or one the visibility review guards) is left out of the re-rank, the
    # new-investment forecast. It keeps bidding at its live bid, though, so its modelled spend goes to rerank_held: the
    # lanes count it as invest spend already planned (the product's band and planned invest, plan_lanes.band_rows),
    # as they did before the visibility review deferred it (merge of 2dcb21c).
    rerank, rerank_held, tot = [], [], defaultdict(float)
    by_kw = {}  # keyed by plan_lanes.row_key: a business row never overwrites the consumer owner's bid, boost and budget
    for x in changes:
        if x['type'] in ('New exact campaign', 'Reuse exact campaign', 'Budget and top of search', 'Bid change') and x.get('role') in ('Invest', 'Prove first'):
            by_kw.setdefault(plan_lanes.row_key(x), {}).update({k: x[k] for k in ('new', 'tos', 'budget') if x.get(k) is not None})
    held_live = {}  # deferred search -> (its highest live exact bid, that keyword's campaign id)
    for p in plan:
        k = norm(p['keyword'])
        if (k in deferred_rank_terms and p['match'] == 'exact' and p['family'] not in ('Audience (low bids)', 'Business') and p['bid']
                and p['bid'] > held_live.get(k, (0, None))[0]):
            held_live[k] = (p['bid'], p['campaign_id'])
    for t in rank_terms:
        r = terms[t]
        days = r['observed_days'] or 84
        tc = r['sqp_total_clicks'] * 30 / days
        our = r['sqp_our_clicks'] * 30 / days
        if t in deferred_rank_terms:
            live_bid, cid = held_live.get(t, (None, None))
            b0, t0, _ = live_budget_tos(cid) if cid else (None, None, [])
            bid, tos, budget = live_bid or r['be_cpc'], t0 or 0, b0 or invest_budget(t, r['sub_role'])
            if t in scheduled_rank_terms and t not in deferred_bid_terms:
                bid = by_kw.get(t, {}).get('new') or bid
        else:
            x = by_kw.get(t, {})
            bid = x.get('new') or r['be_cpc']
            tos = x.get('tos') or 0
            budget = x.get('budget') or invest_budget(t, r['sub_role'])
        cpc = round((bid + bid * (1 + tos / 100)) / 2, 2)
        spend, orders, net, capped = plan_lanes.rerank_cost(tc, cpc, budget, r, bud['rerank_click_share_target'], PROFIT)
        row = dict(product=name, asin=asin, keyword=t, role=r['sub_role'], month_searches=round(evidence.monthly_searches(r['sqp_volume'], days) or 0),
                   month_clicks=round(tc), our_click_share=(our / tc) if tc else None, ad_spend_now=round(r['ad_spend'] / 3, 2),
                   bid=bid, tos=tos, cpc=cpc, budget=budget, spend=round(spend), orders=round(orders, 1),
                   net=round(net), capped=capped)
        if t in deferred_rank_terms:
            reason = ('Base-bid pricing continues; new routing/placement investment waits for scheduled serving.'
                      if t in scheduled_rank_terms and t not in deferred_bid_terms else
                      'Kept at its live bid pending its visibility or rank-experiment review; not part of the new-investment forecast.')
            rerank_held.append(dict(row, held=reason))
            continue
        rerank.append(row)
        tot['now'] += r['ad_spend'] / 3; tot['spend'] += spend; tot['orders'] += orders; tot['net'] += net; tot['budget'] += budget
    # the business invests' re-rank rows (business.rerank_rows; design 4d), after the consumer ones
    ctx.name = name
    rerank.extend(business.rerank_rows(ctx))

    # the season, for the preview and the lanes (a phase switch sends every change to a person, plan_lanes). In a rank build:
    # the most its invest budgets can spend to the build's end, against the block's cap for the whole window
    season_out = None
    if season_now:
        season_out = {k: season_now[k] for k in ('name', 'phase', 'harvest', 'rank_searches', 'switch', 'invest_cap', 'next', 'text')}
        if season_now['phase'] == 'rank build':
            days = (dt.date.fromisoformat(season_now['rank_build_end']) - dt.date.fromisoformat(review_date)).days + 1
            season_out.update(rank_build_days_left=days, rank_build_budget_to_end=round(tot['budget'] * days),
                              over_invest_cap=bool(season_now['invest_cap']) and tot['budget'] * days > season_now['invest_cap'])
            if season_out['over_invest_cap']:
                season_out['text'] += (f"; the invest budgets (${tot['budget']:g}/day for {days} days, up to "
                                       f"${season_out['rank_build_budget_to_end']}) can pass the rank build's ${season_now['invest_cap']:g} cap: "
                                       f"lower them (budget_overrides) or get the cap raised")

    cnt = Counter(x['type'] for x in changes)
    ups = sum(1 for x in changes if x['type'] == 'Bid change' and (x.get('change') or 0) > 0)
    disc = [p for p in plan if p['role'] == 'Discovery' and p['family'] not in ('Audience (low bids)', 'Business')]
    ctx.BUSINESS_COPY_PAUSE = BUSINESS_COPY_PAUSE
    business_out = business.summary(ctx)   # summary.business
    # the organic share, the top-10 rule and the leak check (organic_share.py, decisions 143 and 175). The leak check reads
    # the ordinary campaigns: every campaign in campaign_days.json (SP) and sb_campaign_days.json (the product's own SB
    # campaigns by id; collections are not in sb['campaigns']) that is not a rank campaign (invest_ids, sb_rank_ids) and
    # not B2B; build() plans again with the leaking keywords paused when it trips. It never holds a Prove-first launch
    logged_invest = {norm(k) for k in (cfg.get('invest_log') or {})}
    leak_days = budget_headroom.campaign_days(run, asin) if org_on else None
    sb_leak_days = budget_headroom.sb_campaign_days(run) if org_on else None
    leak_rows = (leak_days or []) + [r for r in sb_leak_days or [] if r['campaign_id'] in sb['campaigns']]
    rank_or_b2b = invest_ids | sb_rank_ids | set(ctx.business_invested)
    leak = organic_share.leak_reading(
        leak_rows, lambda cid, name: cid not in rank_or_b2b and kind(name) != 'business',
        PROFIT, osh, budget_headroom.settings(shared)['settle_days']) if leak_rows else None
    organic_out = dict(
        enabled=org_on, target_share=osh['target_share'], share=share_now, stage=stage_name,
        non_rank_factor=nr, base_factor=nr_base, top10=dict(sorted(top10.items())),
        leak=leak_summary(leak, changes, leak_pause, osh) if leak else None,
        # every invest search (this run's rank searches and the logged ones) with no Rank Radar: the run adds one for each,
        # within the DataDive quota (decision 105), so the top-10 rule and the stop-loss can read it
        radar_missing=sorted(t for t in set(rank_terms) | logged_invest if t not in radar_early) if org_on else [],
        note=('; '.join(n for n in (
            None if not org_on or sales_daily else 'no sales_daily.json in the run folder: the organic share is not reported',
            None if not org_on or leak_days else 'no campaign_days.json in the run folder: the leak check read no Sponsored Products',
            None if not org_on or sb_leak_days is not None or not sb['campaigns'] else
            'no sb_campaign_days.json in the run folder: the leak check read no Sponsored Brands (references/data-pull.md)')
            if n) or None))
    summary = dict(product=name, asin=asin, sku=cfg['sku'], invest=len(rank_terms), rank_reviews_deferred=len(deferred_rank_terms),
                   organic=organic_out,
                   brand_guard=dict(words=brand_keep, searches=brand_searches, dropped_rows=brand_dropped),
                   new_campaigns=cnt['New exact campaign'], reused_campaigns=cnt['Reuse exact campaign'], pauses=cnt['Pause keyword'],
                   bid_changes=cnt['Bid change'], bids_up=ups, bids_down=cnt['Bid change'] - ups,
                   budgets=cnt['Budget and top of search'], budget_steps=cnt['Budget step'], budget_headroom=bh_summary,
                   negatives=cnt['Negative exact'], negatives_skipped=len(skipped),
                   stop_loss_reviews=cnt['Stop-loss review'],
                   stop_loss_step_downs=len({(x.get('owner_kind'), x['keyword']) for x in changes if x.get('stop_loss_step_down')}),
                   invest_now_day=round(tot['now'] / 30, 1), invest_plan_day=round(tot['spend'] / 30, 1),
                   invest_budget_day=round(tot['budget']), discovery_day=round(sum(p['spend90'] for p in disc) / 90, 1),
                   invest_orders_month=round(tot['orders']), invest_net_month=round(tot['net']),
                   asin_ad_cvr=round(ASIN_AD_CVR, 4), asin_market_cvr=round(ASIN_MKT_CVR, 4), profit_per_unit=PROFIT,
                   breakeven_click_avg=round(PROFIT * ASIN_AD_CVR, 2), mode=mode, run=os.path.basename(os.path.abspath(run)),
                   inputs=dict(sqp=len(sq), search_terms=len(st_rows), keywords=len(kw_rows), raw_keyword_rows=raw_keyword_count,
                               suggested=len(sug), contextual_suggestions=len(contextual), campaigns=len(camps), recent=len(recent)),
                   sqp_data_through=sqp_data_through,
                   last_season_sqp=dict(searches=len(LS), data_through=ls_through) if LS else None, sb_video=sb_out, visibility=(visibility_review or {}).get('counts', {}),
                   # every keyword and target priced (decision 135): what the live reads added, what was left out and why,
                   # and the reason a run was planned without them (--partial-inventory)
                   inventory=dict(live_keywords=live_inv['keywords_read'], live_targets=live_inv['targets_read'],
                                  keywords=live_kw_counts, targets=live_t_counts, targets_priced=dict(target_counts),
                                  sponsored_display=sd_status, partial_reason=partial_inventory,
                                  no_data_raise=not never_raise, daypart=daypart_out, ad_group_defaults=dict(ag_counts), shared_campaigns=shared_out),
                   # what the placement policy did with each campaign (decision 155): the coverage ledger reads it
                   placement_policy=dict(enabled=policy_on, set=sorted(policy_tos), kept_boost=dict(kept_boost),
                                         audience_boost=dict(audience_boost),
                                         rank=sorted(c for c in rank_cids if c),
                                         experiments=sorted(str(c.get('campaignId')) for c in camps if in_experiment(c))),
                   # the campaigns this product's ads serve in (decision 156): found by product ad, or left out as multi-ASIN
                   campaign_scope=(dict(read=False) if scope is None else dict(
                       read=True, own=[dict(id=k, name=v['name'], ad_type=v['ad_type']) for k, v in sorted(scope['own'].items())],
                       multi=[dict(id=k, name=v['name'], ad_type=v['ad_type'], asins=v['asins'], spend90=v['spend90'])
                              for k, v in sorted(scope['multi'].items())], sd=sorted(scope['sd']))) | dict(
                       sb_multi=[dict(id=k, name=c.get('name')) for k, c in sorted((sb.get('multi') or {}).items())]),
                   season=season_out, blacklist_rescue=blacklist_out, business=business_out,
                   # the suggested mid (decision 177): every keyword it reached, its state, the mid and where it came from, and
                   # what each spent in its 90 days (the launch test's spend, the rule's ask); None when mid_bid is off
                   mid_bid=mid_summary(plan, sb_mid_of, mid_cfg),
                   # the Hold uplift test's keywords this run (decision 108): the baseline (hold_uplift.py) reads them
                   hold_uplift=(dict(pct=hold_up['pct'], review_on=hold_up.get('review_on'),
                                     keywords=sorted({p['keyword_id'] for p in plan if p.get('hold_uplift')}),
                                     comparison=sorted({p['keyword_id'] for p in plan if p.get('hold_comparison')}))
                                if hold_up and any(p.get('hold_uplift') for p in plan) else None),
                   # the invest searches priced without Amazon's suggestion (decision 106): what was tried, and each search's
                   # source; None when Amazon covered every one
                   bid_fallback=(dict(tried=bids_tried, searches={t: dict(source=k, priced_on=n) for t, (k, n) in sorted(fallback_sources.items())},
                                      business_searches=sorted(getattr(ctx, 'business_fallback', None) or []))
                                 if fallback_sources or getattr(ctx, 'business_fallback', None) else None),
                   # the data stage (stage.py): the stage dict, the volatile-week text (reported at every stage, and it holds
                   # promotions in stage early only; None when lifted with --allow-volatile, the text then under
                   # volatile_week_overridden) and this run's SQP totals
                   size_check=dict(sizes=sorted(sizes), protected=sorted(sizes - own_sizes(asin, cfg)),
                                   live_verification=size_verification,
                                   live_verification_problem=size_verification_problem,
                                   note=None if sizes else 'Product size unknown; size check not applied.'),
                   stage=stage_info, volatile_week=volatile_week,
                   volatile_week_overridden=volatile_text if allow_volatile and volatile_text else None,
                   sqp_totals=stage.sqp_totals(sq_rows))
    # exact SKC ad groups to check for self-blocking negatives before raising their bids
    checks = []
    for p in plan:
        if p['family'] == 'SKC' and p['match'] == 'exact' and p['action'].startswith(('Invest', 'Prove')):
            checks.append(dict(keyword=norm(p['keyword']), campaign_id=p['campaign_id'], ad_group_id=p['ad_group_id']))
    for t, c in reuse.items():
        checks.append(dict(keyword=t, campaign_id=str(c.get('campaignId')), ad_group_id=None))
    # and every business owner's ad group, and the ad group a new business exact keyword goes into (design 4c): the team's
    # B2B ad groups carry Scale Insights negatives (Launch Targets negates a search once it has an order). A new keyword with
    # no campaign to go into (no marker campaign at all) has nothing to check yet: its row says what to do first
    for p in plan:
        if p.get('owner_kind') == 'business' and p['role'] == 'Rank' and p['action'].startswith(('Invest', 'Prove')):
            checks.append(dict(keyword=norm(p['keyword']), campaign_id=p['campaign_id'], ad_group_id=p['ad_group_id']))
    for x in changes:
        if x['type'] == 'New exact keyword' and x.get('owner_kind') == 'business' and x.get('campaign_id'):
            checks.append(dict(keyword=x['keyword'], campaign_id=x['campaign_id'], ad_group_id=x['ad_group_id']))
    # the business owner keyword of each business invest search (design 4c), whatever this run does with it: plan.json
    # leaves the keyword plan out, and log_invest.py records the owner's campaign on a business invest log entry started
    # without a row (its owner held by the visibility review, say), so its stop-loss review has a row id of its own
    business_owners_out = [dict(keyword=t, keyword_id=str(m.get('KeywordId')), campaign_id=str(m.get('CampaignId')),
                                ad_group_id=str(m.get('AdGroupId'))) for t, m in sorted(business_owner.items())]
    out = dict(summary=[summary], changes=changes, rerank=rerank, rerank_held=rerank_held, terms=list(terms.values()),
               business_terms=list(business_terms.values()), business_live_invests=business_live,
               business_owners=business_owners_out, harvest=harvest, skipped_negatives=skipped, checks=checks,
               stop_loss=stop_rows, keyword_plan=plan, target_plan=target_plan, visibility_review=visibility_review,
               # what the coverage ledger checks "priced" against (decision 156); build() takes it off before the plan is saved
               _priced=dict(sb=sorted(sb_priced), ad_groups=sorted(ag_priced)))
    size_holds(changes, sizes, size_verification)
    size_pauses = [r for r in changes if r['type'] in listing_size.PAUSES and r.get('role') == 'Negate'
                   and wrong_size(r.get('keyword'), sizes)]
    summary['size_check'].update(
        confirmed_pauses=sum(bool(r.get(listing_size.MARKER)) for r in size_pauses),
        needs_live_read=bool(size_pauses) and size_verification is None,
        pause_candidates=[dict(type=r['type'], keyword=r.get('keyword'), keyword_id=r.get('keyword_id'))
                          for r in size_pauses if r.get('relevance_hold')])

    # ---- 6. lanes: who has to say yes to each change, the investment bands and apply_after (plan_lanes.py).
    #         main() runs it itself, after its placement refresh, because that refresh re-prices the re-rank the bands use.
    if with_lanes:
        plan_lanes.assign(out, cfg, shared, mode, lane_inputs, today_iso, now_utc)
    return out


# ----------------------------------------------------------------------------- outputs
def payload_entries(ch, shared, asin):
    """The MAP-ready payload files for a set of change rows, each payload row with the rows it came from:
    [(file name, [(row_ids, payload row)])], empty files left out. row_ids lists the row_id of every change row behind
    that payload row: one, except a Sponsored Brands build spec (one per new campaign, holding every keyword row of it) and
    a business invest campaign's update (one per campaign, holding every Business invest and New exact keyword row of it).
    A change can be behind payload rows in several files (a new campaign and its 1b spec; a Business invest's bid, its
    campaign's update and its 2b spec), and a change behind no payload row (a repeat bid on one keyword, a manual row) is in
    none. payload_files and payload_row_ids are both read from here."""
    def ids(c):
        return [c.get('row_id')]
    pauses = [(ids(c), dict(type='sp_keywords', keywordId=c['keyword_id'], state='PAUSED'))
              for c in ch if c['type'] == 'Pause keyword' and c.get('keyword_id')]
    bids = []
    seen = set()
    for c in ch:
        # a Business invest's keyword bid goes out with the other bids (design 4b)
        if c['type'] in ('Bid change', 'Business invest') and c.get('keyword_id') and c['keyword_id'] not in seen:
            seen.add(c['keyword_id'])
            bids.append((ids(c), dict(type='sp_keywords', keywordId=c['keyword_id'], bid=c['new'])))

    def placement_bidding(tos, others):
        """The complete placement list: top of search at tos, every other placement as live."""
        pb = [dict(placement='PLACEMENT_TOP', percentage=int(tos))]
        for o in others or []:
            pl = {'REST_OF_SEARCH': 'PLACEMENT_REST_OF_SEARCH', 'PRODUCT_PAGE': 'PLACEMENT_PRODUCT_PAGE'}.get(o.get('placement'), o.get('placement'))
            pb.append(dict(placement=pl, percentage=int(o.get('percentage') or 0)))
        return pb
    camps = []
    for c in ch:
        if c['type'] == 'Budget step':  # budget only: the campaign's placements and bidding strategy stay as live
            camps.append((ids(c), dict(type='sp_campaigns', campaignId=c['campaign_id'], budget=dict(budget=c['budget'], budgetType='DAILY'))))
            continue
        if c['type'] == 'Budget and top of search':
            if c.get('placement_policy') and c.get('placement_hold'):
                continue   # a placement-policy row whose write can't be made safely writes nothing (its budget is unchanged)
            if c.get('placement_hold'):
                camps.append((ids(c), dict(type='sp_campaigns', campaignId=c['campaign_id'], budget=dict(budget=c['budget'], budgetType='DAILY'))))
                continue
            camps.append((ids(c), dict(type='sp_campaigns', campaignId=c['campaign_id'], budget=dict(budget=c['budget'], budgetType='DAILY'),
                                       dynamicBidding=dict(strategy='LEGACY_FOR_SALES', placementBidding=placement_bidding(c['tos'], c.get('other_placements'))))))
    # the campaign update of the business invests (design 4b, 4c): one per campaign, however many Business invest and
    # New exact keyword rows of it are here, at the campaign-wide top of search and budget stamped on every row of the
    # campaign (stamp_business_campaigns), so any subset of them writes the same update. A held placement
    # (placement_review.hold_defaults) writes no placements, as a held Budget and top of search row; a campaign not read
    # live writes no budget; with neither, no update. A new keyword without an ad group has no payload, so no update either
    for cid, rows in business_campaign_rows(ch).items():
        tos = [v for v in (c['campaign_tos'] if 'campaign_tos' in c else c.get('tos') for c in rows) if v is not None]
        budgets = [v for v in (c['campaign_budget'] if 'campaign_budget' in c else
                               (c.get('budget') if c.get('budget_now') is not None else None) for c in rows) if v is not None]
        update = dict(type='sp_campaigns', campaignId=cid)
        if budgets:
            update['budget'] = dict(budget=max(budgets), budgetType='DAILY')
        if tos and not any(c.get('placement_hold') for c in rows):
            update['dynamicBidding'] = dict(strategy='LEGACY_FOR_SALES', placementBidding=placement_bidding(max(tos), rows[0].get('other_placements')))
        if 'budget' in update or 'dynamicBidding' in update:
            camps.append(([c.get('row_id') for c in rows], update))
    new_c = [(ids(c), dict(type='sp_campaigns', name=c['campaign'], state='ENABLED', targetingType='MANUAL',
                           budget=dict(budget=c['budget'], budgetType='DAILY'), portfolioId=shared['portfolio_id'],
                           dynamicBidding=dict(strategy='LEGACY_FOR_SALES', placementBidding=[dict(placement='PLACEMENT_TOP', percentage=int(c['tos']))])))
             for c in ch if c['type'] == 'New exact campaign']
    def reuse_placement(c):
        if c.get('placement_hold'):
            return {'placement_hold': True, 'instruction': 'Preserve all live placement modifiers, audience adjustments and bidding strategy.'}
        if c.get('other_placements') is None:
            return {'tos': c['tos']}
        # the standing rank policy (placement_review.hold_defaults): top of search is the policy, every other modifier as live
        return {'tos': c['tos'], 'other_placements': c['other_placements'],
                'instruction': 'Set top of search to tos; keep the other placement modifiers listed, the audience adjustments and the bidding strategy exactly as live.'}
    reuse = [(ids(c), dict(campaign_id=c['campaign_id'], keyword=c['keyword'], bid=c['new'], budget=c['budget'], **reuse_placement(c)))
             for c in ch if c['type'] == 'Reuse exact campaign']
    # a Business invest's own spec, as a reuse row's (its writes are the bid above and its campaign's single update), at the
    # campaign-wide top of search and budget, so a spec applied on its own can't undo another invest of the campaign either;
    # no budget when the campaign wasn't read live
    def business_spec(c):
        budget = c['campaign_budget'] if 'campaign_budget' in c else (c['budget'] if c.get('budget_now') is not None else None)
        spec = dict(campaign_id=c['campaign_id'], ad_group_id=c['ad_group_id'], keyword_id=c['keyword_id'], keyword=c['keyword'],
                    bid=c['new'], budget=budget, **reuse_placement(dict(c, tos=c.get('campaign_tos', c.get('tos')))))
        if budget is None:
            spec['budget_note'] = 'The campaign was not read live: leave its budget as it is; check it before any change.'
        return spec
    business_specs = [(ids(c), business_spec(c)) for c in ch if c['type'] == 'Business invest']
    # a business invest search's new exact keyword, added to the team's B2B exact campaign (design 4c)
    new_keywords = [(ids(c), dict(type='sp_keywords', campaignId=c['campaign_id'], adGroupId=c['ad_group_id'], keywordText=c['keyword'],
                                  matchType='EXACT', bid=c['new'], state='ENABLED'))
                    for c in ch if c['type'] == 'New exact keyword' and c.get('owner_kind') == 'business'
                    and c.get('campaign_id') and c.get('ad_group_id')]
    negs = [(ids(c), dict(type='sp_negative_keywords', campaignId=c['campaign_id'], adGroupId=c['ad_group_id'], keywordText=c['keyword'],
                          matchType='EXACT', state='ENABLED')) for c in ch if c['type'] == 'Negative exact']
    harvest = [(ids(c), dict(type='sp_ad_groups', adGroupId=c['ad_group_id'], defaultBid=c['new'])) for c in ch
               if c['type'] in ('Harvest default bid', 'Ad group default bid')]
    # Sponsored Brands video: one build spec per new campaign. Create in this order, each step using the ids the last one
    # returned: campaign, ad group, video ad, keywords (references/map-playbook.md). startDate = the day you apply.
    sbv = shared.get('sb_video') or {}
    sb_specs = {}
    for c in ch:
        if c['type'] != 'New SB video campaign':
            continue
        spec_ids, spec = sb_specs.setdefault(c['campaign'], ([], dict(
            campaign=dict(type='sb_campaigns', name=c['campaign'], budget=c['budget'], budgetType='DAILY', startDate='<apply day>',
                          state='ENABLED', goal='PAGE_VISIT', costType='CPC', smartDefault=['MANUAL'], bidding=dict(bidOptimization=False)),
            ad_group=dict(type='sb_ad_groups', campaignId='<campaignId>', name=c['campaign'], defaultBid=c['new'], state='ENABLED'),
            ad=dict(type='sb_ads', adType='video', adGroupId='<adGroupId>', name=c['campaign'], state='ENABLED',
                    creative=dict(videoAssetIds=[c.get('video_asset') or '<MISSING: product sb_video.video_asset_id>'], asins=[asin])),
            keywords=[], portfolio=sbv.get('portfolio_name', '3. Video Ads - Normal Bids'))))
        spec_ids.append(c.get('row_id'))
        spec['keywords'].append(dict(type='sb_keywords', campaignId='<campaignId>', adGroupId='<adGroupId>', keywordText=c['keyword'],
                                     matchType='EXACT', bid=c['new']))
    sb_kw = [(ids(c), dict(type='sb_keywords', keywordId=c['keyword_id'], adGroupId=c['ad_group_id'], campaignId=c['campaign_id'], bid=c['new']))
             for c in ch if c['type'] == 'SB bid change' and not c.get('target_id') and not c.get('theme_id')]
    sb_kw += [(ids(c), dict(type='sb_keywords', keywordId=c['keyword_id'], adGroupId=c['ad_group_id'], campaignId=c['campaign_id'], state='PAUSED'))
              for c in ch if c['type'] == 'SB pause keyword']
    sb_t = [(ids(c), dict(type='sb_targets', targetId=c['target_id'], adGroupId=c['ad_group_id'], campaignId=c['campaign_id'], bid=c['new']))
            for c in ch if c['type'] == 'SB bid change' and c.get('target_id')]
    sb_th = [(ids(c), dict(type='sb_themes', themeId=c['theme_id'], adGroupId=c['ad_group_id'], campaignId=c['campaign_id'], bid=c['new']))
             for c in ch if c['type'] == 'SB bid change' and c.get('theme_id')]
    sb_opt = [(ids(c), dict(type='sb_campaigns', campaignId=c['campaign_id'],
                            bidding=dict(bidOptimization=False, **({'bidAdjustmentsByPlacement': c['placements']} if c.get('placements') else {}))))
              for c in ch if c['type'] == 'SB bid optimisation']
    # a Sponsored Display target (ad_product SD, decision 135) is an sd_targets update: a numeric id, a lowercase state
    t_bids = [(ids(c), dict(type='sp_targets', targetId=c['target_id'], bid=c['new'])) for c in ch
              if c['type'] == 'Target bid change' and c.get('ad_product') != 'SD']
    t_pauses = [(ids(c), dict(type='sp_targets', targetId=c['target_id'], state='PAUSED')) for c in ch
                if c['type'] == 'Pause target' and c.get('ad_product') != 'SD']
    sd_t = [(ids(c), dict(type='sd_targets', targetId=int(c['target_id']), state='paused')) for c in ch
            if c['type'] == 'Pause target' and c.get('ad_product') == 'SD']
    sd_t += [(ids(c), dict(type='sd_targets', targetId=int(c['target_id']), bid=c['new'])) for c in ch
             if c['type'] == 'Target bid change' and c.get('ad_product') == 'SD']
    # down-only bidding (decision 140): MAP's optimizations shape, every live placement and audience adjustment sent back
    # as read, so only the strategy changes. The product-page base bid (placement_shape.py): the same shape, at down only,
    # with the campaign's new top-of-search, rest-of-search and product-page modifiers and every other live placement as read
    strategy = [(ids(c), dict(type='sp_campaigns', campaignId=c['campaign_id'],
                              optimizations=dict(bidSettings=dict(bidStrategy=c['strategy'],
                                                                  bidAdjustments=c.get('bid_adjustments') or {}))))
                for c in ch if c['type'] == 'Bidding strategy']
    shape = [(ids(c), dict(type='sp_campaigns', campaignId=c['campaign_id'],
                           optimizations=dict(bidSettings=dict(bidStrategy='SALES_DOWN_ONLY',
                                                               bidAdjustments=c['bid_adjustments']))))
             for c in ch if c['type'] == 'Placement shape']
    out = [('1_new_campaigns.json', new_c),
           ('1b_new_skc_specs.json', [(ids(c), dict(keyword=c['keyword'], campaign=c['campaign'], bid=c['new'], sku=None))
                                      for c in ch if c['type'] == 'New exact campaign']),
           ('1c_new_keywords.json', new_keywords), ('2_reuse_specs.json', reuse),
           ('2b_business_invest_specs.json', business_specs), ('3_pauses.json', pauses)]
    out += [(f'4_bids_{i // 120 + 1:02d}.json', bids[i:i + 120]) for i in range(0, len(bids), 120)]
    out.append(('5_campaign_updates.json', camps + harvest))
    out.append(('5b_bidding_strategy.json', strategy))
    out += [(f'6_negatives_{i // 100 + 1:02d}.json', negs[i:i + 100]) for i in range(0, len(negs), 100)]
    out += [('7_sb_new_campaigns.json', list(sb_specs.values())), ('8_sb_keyword_updates.json', sb_kw),
            ('8b_sb_target_updates.json', sb_t), ('8c_sb_bid_optimisation.json', sb_opt), ('8d_sb_theme_updates.json', sb_th), ('9_target_pauses.json', t_pauses)]
    out += [(f'9_target_bids_{i // 120 + 1:02d}.json', t_bids[i:i + 120]) for i in range(0, len(t_bids), 120)]
    out += [(f'9b_sd_target_updates_{i // 100 + 1:02d}.json', sd_t[i:i + 100]) for i in range(0, len(sd_t), 100)]
    # last: a shaped campaign's modifiers go up only after its lower base bids (4_bids, 9_target_bids) are in
    out.append(('9c_placement_shape.json', shape))
    return [(fname, arr) for fname, arr in out if arr]


def payload_files(ch, shared, asin):
    """The MAP-ready payload files for a set of change rows: [(file name, rows)], empty files left out."""
    return [(fname, [row for _, row in pairs]) for fname, pairs in payload_entries(ch, shared, asin)]


def payload_row_ids(ch, shared, asin):
    """{file name: [row_id behind each payload row, in order]} for the files payload_files writes: the rows.json written
    next to every payload folder. A Sponsored Brands build spec lists the row_id of each keyword row it holds, and a business
    invest campaign's update the row_id of each row of that campaign, so those files' lists can be longer than their payload
    rows; every other file has one row_id per payload row."""
    return {fname: [rid for row_ids, _ in pairs for rid in row_ids] for fname, pairs in payload_entries(ch, shared, asin)}


FETCH_REQUESTS = ('need_suggested_bids.json', 'need_suggested_bids_business.json', 'need_sb_keywords.json')  # main() clears them
LANE_FOLDERS = ('auto', 'review', 'held')  # write_outputs' payload folders; approved/ belongs to dashboard.py approvals
# whether a folder's files need a person's yes before they are applied (autonomous runs, Kim 2026-10-22): auto/ is
# applied by the run itself, review/ after a person's yes, held/ never (None)
APPROVAL_REQUIRED = {'auto': False, 'review': True, 'held': None}
SI_STEPS = autonomy.SI_STEPS  # a lane folder's Scale Insights checklist (not a MAP payload)
SI_STEP_KEYS = ('row_id', 'type', 'keyword', 'item', 'current', 'new', 'why', 'how', 'owner_kind', 'exact_remove',
                'phrase_remove', 'whitelist_add', 'si_beyond_standard', 'asin', 'campaign_id', 'ad_group_id',
                'scope_entities', 'shared_product_lists_unaffected', 'scope_evidence')


def scale_insights_steps(rows):
    """The Scale Insights rows of a lane folder as the browser step's checklist: one entry per row, with what to do (item,
    current, new, how) and why, and a blacklist rescue's lists."""
    return [{k: c[k] for k in SI_STEP_KEYS if c.get(k) not in (None, '', [])} for c in rows
            if c.get('type') in ('Scale Insights rules', 'Scale Insights setup') and c.get('row_id')]


def as_written(change):
    """The change as its payload writes it: a bid the auto lane caps (`new_capped`, kept on a shadow run's automatic rows
    and on a raise held back only for the run's cap) is written at the cap, and a bid in a campaign the product-page base
    bid shapes (`shape_base`, placement_shape.py, decision 140) at its shaped base. A copy; the plan row stays as it is."""
    capped, base = change.get('new_capped'), change.get('shape_base')
    if base is not None:
        return dict(change, new=base)
    return change if capped is None else dict(change, new=capped)


def write_outputs(run, out, shared, asin):
    """plan.json, terms.csv, changes.csv, checks.json, visibility_review.json and need_visibility_data.json (when the
    visibility review ran), growth.json (out['growth_run'], the For Growth step main() runs: plan_growth; kept out of
    plan.json, whose human_review already holds the item), the payloads, split by lane into payloads/auto, payloads/review
    and payloads/held, and payload_manifest.json.

    A row a lock holds (plan_lanes stamps locked_until) and a row the planner holds until the next run (monitor) can't go
    out: they go to held/ only, so a person can see what was held, in both modes (B10: a whole-run yes on a shadow preview
    can't apply what the planner holds). Of the rest: in shadow (summary.shadow not exactly False) review/ gets every row
    and auto/ nothing; enabled, auto rows go to auto/ and the others to review/. A row with no lane counts as human. Every
    folder writes each row as_written: a bid the auto lane caps is written at the cap. A folder with payloads also gets
    rows.json, {file name: [row_id behind each payload row]}.

    Visibility experiments and rank-investment proposals are preview-only: a plan holding one is refused before anything
    is written. A re-plan of the run folder moves the earlier plan's payloads to payload_archive/<SGT time>/ (top-level
    payloads/*.json from a run planned before the lanes, and everything in auto/, review/ and held/), so nothing of an
    earlier plan is left where it could be applied. payload_manifest.json lists the current payload files of auto/ and
    review/ (`files`: path under payloads/, folder, rows, sha256) and of held/ apart (`held_files`, never applied); it is
    an inventory (visibility.md).

    Autonomous runs (Kim, 2026-10-22, decision 98): the manifest says which folder needs a person. `approval_required`
    is {auto: False, review: True, held: None}, and each file carries its folder's flag: auto/ is applied by the run itself
    during the audit (only an enabled product's auto/ holds rows), review/ only after a person's yes, held/ never. The
    Scale Insights rows of a lane folder ('Scale Insights rules' and 'Scale Insights setup', which have no MAP payload) are
    written as an executable checklist for the browser step, scale_insights_steps.json (row_id, item, current, new, why,
    how, and a blacklist rescue's lists), with their row ids in rows.json, so `dashboard.py applied` records them like any
    row once they are done and read back; its manifest entry says apply_via 'Scale Insights web app'."""
    if any(row.get('visibility_experiment') or row.get('type') == 'Visibility experiment' for row in out['changes']):
        raise ValueError('Visibility experiments are preview-only; approve the concrete experiment and recheck live state before preparing apply payloads.')
    if any(row.get('rank_investment_experiment') for row in out['changes']):
        raise ValueError('Rank-investment proposals are preview-only; rebuild apply payloads after separate launch approval and live checks.')
    payload_directory = os.path.join(run, 'payloads')
    generated_pattern = r'(1_new_campaigns|1b_new_skc_specs|1c_new_keywords|2_reuse_specs|2b_business_invest_specs|3_pauses|4_bids_\d+|5_campaign_updates|6_negatives_\d+|7_sb_new_campaigns|8_sb_keyword_updates|9_target_pauses|9_target_bids_\d+|9b_sd_target_updates_\d+)\.json'
    old_payloads = [(path, '') for path in glob.glob(os.path.join(glob.escape(payload_directory), '*.json'))
                    if re.fullmatch(generated_pattern, os.path.basename(path))]
    for folder in LANE_FOLDERS:  # a re-plan of this run folder must not leave an earlier plan's payloads behind
        old_payloads += [(path, folder) for path in glob.glob(os.path.join(glob.escape(payload_directory), folder, '*.json'))]
    if old_payloads:
        stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime('%Y%m%dT%H%M%S%f+0800')
        archive = os.path.join(run, 'payload_archive', stamp)
        os.makedirs(archive, exist_ok=False)
        for path, folder in old_payloads:
            os.makedirs(os.path.join(archive, folder), exist_ok=True)
            shutil.move(path, os.path.join(archive, folder, os.path.basename(path)))
    os.makedirs(payload_directory, exist_ok=True)
    plan_path = os.path.join(run, 'plan.json')
    keep = {k: v for k, v in out.items() if k not in ('keyword_plan', 'target_plan', 'growth_run')}
    write_json(plan_path, keep, ensure_ascii=False, default=str, indent=0)
    if out.get('growth_run') is not None:
        write_json(os.path.join(run, 'growth.json'), out['growth_run'], ensure_ascii=False, default=str, indent=1)
    with open(os.path.join(run, 'terms.csv'), 'w', newline='', encoding='utf-8') as fh:
        cols = ['term', 'role', 'sub_role', 'index', 'index_basis', 'sqp_volume', 'sqp_our_clicks', 'sqp_our_purchases', 'ad_clicks',
                'ad_orders', 'ad_spend', 'cvr_est', 'be_cpc', 'impression_share', 'organic_share', 'why',
                'stage', 'volume_basis', 'relevance_flag', 'fallback_index', 'sqp_observed_days']   # the data stage (2026-10-22)
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore'); w.writeheader()
        for r in sorted(out['terms'], key=lambda r: (r['role'], -(r['sqp_volume'] or 0))):
            w.writerow(r)
    with open(os.path.join(run, 'changes.csv'), 'w', newline='', encoding='utf-8') as fh:
        cols = ['step', 'type', 'keyword', 'match', 'role', 'campaign', 'current', 'new', 'tos', 'budget', 'budget_now', 'tos_now',
                'clicks90', 'orders90', 'spend90', 'why', 'keyword_id', 'campaign_id', 'ad_group_id',
                'lane', 'lane_reason', 'confidence_text', 'opportunity', 'new_proposed', 'row_id']
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore'); w.writeheader()
        for c in out['changes']:
            w.writerow(c)
    write_json(os.path.join(run, 'checks.json'), out['checks'], indent=1)
    size_check = (out.get('summary') or [{}])[0].get('size_check') or {}
    write_json(os.path.join(run, 'need_listing_size_verification.json'), dict(
        asin=asin, needs_live_read=bool(size_check.get('needs_live_read')),
        rows=size_check.get('pause_candidates', []) if size_check.get('needs_live_read') else [],
        reason=size_check.get('live_verification_problem'),
        how='Read the live listing, save raw evidence and listing_size_verification.json, then re-plan before apply; '
            'references/live-size-pauses.md. Missing evidence is AI research, not a request for another approval.'), indent=1)
    # this run's SQP totals and their date (stage.sqp_totals): dashboard.py appends them to the product file's sqp_history, the
    # next run's baseline for the volatile-week check (data-stage design 4.6)
    first = (out.get('summary') or [{}])[0]
    if first.get('sqp_totals') is not None:
        write_json(os.path.join(run, 'sqp_totals.json'), dict(first['sqp_totals'], data_through=first.get('sqp_data_through')), indent=1)
    if out.get('visibility_review'):
        write_json(os.path.join(run, 'visibility_review.json'), out['visibility_review'], ensure_ascii=False, indent=2)
        write_json(os.path.join(run, 'need_visibility_data.json'), out['visibility_review'].get('missing_requests', []),
                   ensure_ascii=False, indent=2)

    ch = out['changes']
    shadow = (out.get('summary') or [{}])[0].get('shadow') is not False
    held = [c for c in ch if c.get('locked_until') or c.get('lane') == 'monitor']
    free = [c for c in ch if not (c.get('locked_until') or c.get('lane') == 'monitor')]
    lanes_to = dict(auto=[] if shadow else [c for c in free if c.get('lane') == 'auto'],
                    review=free if shadow else [c for c in free if c.get('lane') != 'auto'],
                    held=held)
    written = {}
    for folder, rows in lanes_to.items():
        P = os.path.join(payload_directory, folder)
        os.makedirs(P, exist_ok=True)  # its earlier plan's files were archived above
        rows = [as_written(c) for c in rows]
        for fname, arr in payload_files(rows, shared, asin):
            write_json(os.path.join(P, fname), arr, separators=(',', ':'))
            written[f'{folder}/{fname}'] = len(arr)
        ids = payload_row_ids(rows, shared, asin)
        # the Scale Insights rows: an executable checklist for the browser step (scale-insights-playbook.md), recorded like
        # any row once done (autonomous runs, 2026-10-22)
        steps = scale_insights_steps(rows)
        if steps:
            write_json(os.path.join(P, SI_STEPS), steps, ensure_ascii=False, indent=1)
            written[f'{folder}/{SI_STEPS}'] = len(steps)
            ids[SI_STEPS] = [s['row_id'] for s in steps]
        if ids:
            write_json(os.path.join(P, 'rows.json'), ids, indent=1)
    # the inventory of what this plan wrote (Codex's manifest, by lane folder): apply only these files, with these hashes,
    # and only by their folder's rule (auto/ by the run itself on any day, no approval needed since
    # 2026-10-22; review/ after a person's yes); held/ is listed apart and never applied
    manifest = dict(asin=asin, approval_required=dict(APPROVAL_REQUIRED), shadow=shadow, files=[], held_files=[])
    for path, count in written.items():
        with open(os.path.join(payload_directory, path), 'rb') as payload:
            digest = hashlib.sha256(payload.read()).hexdigest()
        folder = path.split('/', 1)[0]
        entry = dict(file=path, folder=folder, rows=count, sha256=digest, approval_required=APPROVAL_REQUIRED[folder])
        if path.endswith('/' + SI_STEPS):
            entry['apply_via'] = 'Scale Insights web app (references/scale-insights-playbook.md)'
        manifest['held_files' if folder == 'held' else 'files'].append(entry)
    write_json(os.path.join(run, 'payload_manifest.json'), manifest, indent=2)
    return plan_path, written


def inventory_problem(run, asin, shared):
    """Why this run can't price every keyword and target yet (config inventory.required; Kim, 2026-10-25, decision 135:
    "we'll price every single keywords now, leaving none behind"), or None. Writes need_live_inventory.json with the reads
    still missing: the product's live Sponsored Products keywords and targets by campaign id groups (from campaigns.json),
    its Sponsored Display targets, and the SD campaigns those name (references/data-pull.md, "Live inventory")."""
    if not (shared.get('inventory') or {}).get('required'):
        return None
    inv = shared.get('inventory') or {}
    scope = load_ad_campaigns(run, asin) if inv.get('ad_campaigns') else None
    camps = []
    p = os.path.join(run, 'campaigns.json')
    if os.path.exists(p):
        t = load_raw(p)
        camps = [c for c in (t.get('items', t) if isinstance(t, dict) else t) if in_scope(asin, c.get('name'), c.get('campaignId'), scope)]
    # this product's campaigns named without its ASIN (decision 156): their live records, read by id, join the groups below
    own_sp = sorted(k for k, v in ((scope or {}).get('own') or {}).items() if v['ad_type'] == 'SP')
    camps += [c for p in files(run, 'own_campaigns') for c in load_items(p) if str(c.get('campaignId')) in own_sp]
    if inv.get('shared_campaigns'):
        camps += [c for p in files(run, 'shared_campaigns') for c in load_items(p)]   # the ones the product file lists (decision 155)
    # with inventory.paused (decision 155) the paused campaigns are read too: their keywords and targets are priced cut only
    states = ('ENABLED', 'PAUSED') if inv.get('paused') else ('ENABLED',)
    enabled = sorted(str(c.get('campaignId')) for c in camps if (c.get('state') or '').upper() in states)
    groups = [','.join(enabled[i:i + 100]) for i in range(0, len(enabled), 100)]
    need = {}

    if inv.get('ad_campaigns') and scope is None:
        need['ad_campaigns'] = ('MAP run_report_sql: the two "Campaigns by product ad" queries of references/data-pull.md '
                                '(Sponsored Products and Sponsored Display, 90 days), saved as ad_campaigns_p1.json and '
                                'ad_campaigns_p2.json')
    elif own_sp and not files(run, 'own_campaigns'):
        need['own_campaigns'] = dict(campaign_ids=','.join(own_sp), how='MAP list_resources sp_campaigns, filters {campaign_id: '
                                     '<these ids>, state_filter: "ALL"}, saved as own_campaigns.json: campaigns of this '
                                     "product named without its ASIN (decision 156)")
    if not camps:
        need['campaigns'] = 'MAP list_resources sp_campaigns, saved as campaigns.json (references/data-pull.md)'
    if not files(run, 'live_keywords'):
        need['live_keywords'] = dict(campaign_id_groups=groups, how='MAP list_resources sp_keywords, filters {campaign_id: <one '
                                     'group>, state_filter: "ENABLED,PAUSED", max_results: 1000}; every page of every group saved '
                                     'as live_keywords_p1.json, live_keywords_p2.json, ...')
    if not files(run, 'live_targets'):
        need['live_targets'] = dict(campaign_id_groups=groups, how='MAP list_resources sp_targets, filters {campaign_id: <one '
                                    'group>, state_filter: "ENABLED,PAUSED", max_results: 1000}; every page saved as '
                                    'live_targets_p1.json, ...')
    tcfg = shared.get('targets') or {}
    if tcfg.get('enabled', True) and tcfg.get('sd'):
        if not files(run, 'sd_targets'):
            need['sd_targets'] = ('Scale Insights get_target_performance asin_list [ASIN], ad_type "SD", days 90, mode "raw", '
                                  'count 500, sort_by "cost", every page saved as sd_targets_p1.json, ...')
        else:
            missing = load_sd_targets(run, asin, tuple(tcfg.get('sd_skip_cost_types') or ('vcpm',)), scope)[2]
            sd_ids = sorted((scope or {}).get('sd') or ())
            if sd_ids and not files(run, 'live_sd_targets'):
                need['live_sd_targets'] = dict(campaign_id_groups=[','.join(sd_ids[i:i + 100]) for i in range(0, len(sd_ids), 100)],
                                               how='MAP list_resources sd_targets, filters {campaign_id_filter: <one group>, '
                                                   'state_filter: "enabled,paused", max_results: 500}; every page saved as '
                                                   'live_sd_targets_p1.json, ... (decision 156)')
            if missing:
                need['sd_campaigns'] = dict(campaign_id_groups=[','.join(missing[i:i + 100]) for i in range(0, len(missing), 100)],
                                            how='MAP list_resources sd_campaigns, filters {campaign_id_filter: <one group>}; '
                                                'saved as sd_campaigns_p1.json, ...')
    if not need:
        return None
    write_json(os.path.join(run, 'need_live_inventory.json'), dict(asin=asin, need=need), indent=1)
    return (f"the live inventory isn't read yet ({', '.join(need)}): see need_live_inventory.json, so not every keyword and "
            'target can be priced')


def went_out_problem(run):
    """Why this run folder must not be planned again (C8, N6), in words, or None. A folder whose payloads went out (partly
    or whole: `dashboard.py applied` wrote payloads/applied_rows.json, even an empty one) would hand the same rows out
    again; one whose approvals were handed out (payloads/approved/rows.json names rows) would no longer hold the plan
    they were approved from."""
    payloads = os.path.join(run, 'payloads')
    if os.path.exists(os.path.join(payloads, 'applied_rows.json')):
        return (f'{run}: this run already went out (partly or whole); plan in a new run folder '
                '(payloads/applied_rows.json records what went out)')
    rows = os.path.join(payloads, 'approved', 'rows.json')
    try:
        handed = read_json(rows) if os.path.exists(rows) else {}
    except (OSError, ValueError):
        handed = {'unreadable': ['rows.json']}  # can't tell what it names: the safe side
    if not isinstance(handed, dict) or any(handed.values()):
        return (f"{run}: this run's approvals were handed out for an apply (payloads/approved/) and aren't recorded as gone "
                'out; plan in a new run folder')
    return None


def saved_reviews_problem(path, asin, review_date):
    """Why <run>/reviews.json can't stand in for the team's decisions today (C6), in words, or None when it can (or when it
    can't be read at all: the lanes step then sends every change to a person, B2).

    It must be the dated shape `dashboard.py reviews --save` writes, {asin, saved_at, entries}, for this ASIN, saved no
    more than a day (Singapore time) before the run's review date. A bare list (an older save) has no saved_at, so it
    counts as stale."""
    again = f'save the dashboard decisions again: python scripts/dashboard.py reviews --asin {asin} --save {path}'
    try:
        saved = load_raw(path)
    except (OSError, ValueError):
        return None
    if isinstance(saved, list):
        return f"{path} doesn't say when it was saved (an older save, a bare list of decisions): {again}"
    if not isinstance(saved, dict):
        return None
    if saved.get('asin') != asin:
        return f"{path} holds the decisions for {saved.get('asin')!r}, not {asin}: {again}"
    at = plan_lanes._moment(saved.get('saved_at'))
    if at is None:
        return f"{path} has no saved_at that can be read, so its age can't be told: {again}"
    day = (at + plan_lanes.SGT).date()
    if day < dt.date.fromisoformat(review_date) - dt.timedelta(days=1):
        return f"{path} was saved on {day} (Singapore), more than a day before this run's {review_date}: {again}"
    return None


def plan_growth(out, cfg, shared, asin, listing, clicks, today_iso):
    """The For Growth step of a run (growth.py; docs/superpowers/specs/2026-10-22-for-growth-tab-design.md sections 1 to 4).
    It reads the product file (`cfg`) and never writes it: dashboard.py stores what growth.json carries.

    - The anchor: the product file's growth.anchor when it holds one (a hand-set one above all), else growth.anchor from
      the Monday launch date and this run's click series (`clicks`, clicks_daily.json). The due dates are read from a
      copy of the product carrying it.
    - The candidates (the evidence gate's run-to-run counts): advanced from growth.candidates by this run, on every run,
      whether or not a trigger fires and whether or not the product is enabled (R4), so enabling it later does not start
      from zero.
    - The trigger (growth.trigger_for, given the candidates as the file holds them): when one fires, the item is built.
      Over an item not yet closed (only a rotate-out flag fires then) it is updated in place: its status, status_by,
      status_at, owner and history are kept and the flag gets a history line (R7). Over a closed one (resolved or
      dismissed) the new item is born open, with the history kept and a line for the new pass (R11); it is built over
      the closed item, so a dismissal's flags stay held through the hold (R43, R49). Without a trigger
      the stored item, if any, is carried as it is.

    Returns (the item for plan.json's human_review, or None; growth.json's dict). growth.json holds the block's JSON form
    at top level when an item was produced this run (growth.block_json, the keys Growth's growth_block.py reads), plus
    asin, item (the item produced this run, else None), trigger, trigger_reason, anchor, next_pass and candidates: none
    of them a list, since the reader stops on an unknown top-level list (R3)."""
    g = cfg.get('growth') if isinstance(cfg.get('growth'), dict) else {}
    stored = g.get('anchor')
    if isinstance(stored, dict) and stored.get('date'):
        the_anchor = stored
    else:
        rows = (clicks or {}).get('rows')
        the_anchor = growth.anchor(cfg, rows if isinstance(rows, list) else None, (clicks or {}).get('since'))
    dated = dict(cfg, growth=dict(g, anchor=the_anchor))
    previous = next((i for i in cfg.get('human_review') or [] if isinstance(i, dict) and i.get('id') == growth.GROWTH_ID),
                    None)
    trigger, reason = growth.trigger_for(dated, out, listing, previous, today_iso, shared)
    candidates = growth.advance_candidates(g.get('candidates'),
                                           growth.gate_candidates(out, listing, dated, shared, today_iso))
    item = None
    if trigger:
        closed = growth.closed(previous)
        item = growth.build_item(asin, out, dated, shared, listing, today_iso, trigger,
                                 previous=previous, trigger_reason=reason, candidates=candidates)
        if previous is not None:
            why = item['workflow']['why']
            if closed:
                note = f"{item['growth']['pass']} raised ({trigger}): {why}"
            else:
                for field in ('status_by', 'status_at', 'owner'):
                    if field in previous:
                        item[field] = copy.deepcopy(previous[field])
                note = f'{why}: the block was refreshed on the open item, its status kept'
            item['history'] = copy.deepcopy(previous.get('history') or []) + [
                dict(date=today_iso, status=item['status'], owner=item.get('owner'), note=note)]
    doc = dict(growth.block_json(item)) if item else {}
    doc.update(asin=asin, item=item, trigger=trigger, trigger_reason=reason, anchor=the_anchor,
               next_pass=growth.due_dates(dated, shared)['next_pass'], candidates=candidates)
    return item or previous, doc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--asin', required=True)
    ap.add_argument('--run', required=True, help='run folder holding the raw pulls')
    ap.add_argument('--mode', choices=['weekly', 'onboard'], default='weekly')
    ap.add_argument('--skill', default=os.path.dirname(HERE))
    ap.add_argument('--data', help='shared data folder holding asins/<ASIN>.json (default: config.json data_dir, else <skill>/data)')
    ap.add_argument('--today', help='YYYY-MM-DD; defaults to today (used for stop-loss ages)')
    ap.add_argument('--no-reviews', metavar='REASON',
                    help="plan without <run>/reviews.json (the dashboard can't be read): every change then goes to a person, "
                         'with this reason, except the rows the planner holds anyway (monitor), which stay in held/')
    ap.add_argument('--partial-inventory', metavar='REASON',
                    help="plan without the live keyword and target reads need_live_inventory.json lists (config inventory, "
                         'decision 135): the keywords and targets Scale Insights has no 90-day row for are then not priced, '
                         'and the summary keeps this reason')
    ap.add_argument('--accept-unowned', metavar='REASON',
                    help='plan although the coverage ledger found live entities no rule owns (decision 155): the summary '
                         'keeps this reason as coverage.accepted')
    ap.add_argument('--allow-volatile', action='store_true',
                    help='plan promotions in a volatile SQP week (one that added more of our clicks than every earlier week, '
                         'summary.volatile_week): the hold applies in stage early only, and a person lifts it; the summary keeps '
                         'the text as volatile_week_overridden')
    a = ap.parse_args()
    problem = went_out_problem(a.run)  # C8: never plan over what went out, or was handed out
    if problem:
        sys.exit(f'{problem}. Nothing planned.')
    shared = read_json(os.path.join(a.skill, 'config.json'))
    if a.partial_inventory is not None and not a.partial_inventory.strip():
        sys.exit('--partial-inventory needs the reason the live inventory is not read. Nothing planned.')
    if a.partial_inventory is None:
        problem = inventory_problem(a.run, a.asin, shared)
        if problem:
            sys.exit(f'{problem}. Read them and rerun, or plan with --partial-inventory "<why>". Nothing planned.')
    data_dir = a.data or shared.get('data_dir') or os.path.join(a.skill, 'data')
    shared['data_dir'] = data_dir  # budget_headroom reads its ledger (budget_steps.json) from the same folder
    cfg_path = os.path.join(data_dir, 'asins', f'{a.asin}.json')
    if not os.path.exists(cfg_path):
        sys.exit(f'No product config at {cfg_path}. Create it first (references/onboarding.md, step 1).')
    cfg = read_json(cfg_path)
    review_date = a.today or sgt_today()
    # the referral fee Amazon charges, read from the settlement report before anything is priced (decision 169): a settled
    # rate on enough units moves profit_per_unit, and the product file keeps the rate, its window and its unit count
    before = copy.deepcopy(cfg)
    ref, problem = referral.refresh(cfg, shared, a.run, a.asin, review_date)
    if problem:
        sys.exit(f'{problem}. Read it and rerun. Nothing planned.')
    if cfg != before:
        autonomy.write_product(cfg_path, cfg)
    # B2, C5 (I1, N4): the team's decisions must reach this plan, as locks, whenever the product has had a bids item,
    # whatever its status (a closed item's declines live only on the dashboard); without the saved file they would be
    # planned over. C6 (N5): the saved file must be this product's, and from today or yesterday.
    bids = [i.get('id') for i in cfg.get('human_review') or [] if isinstance(i, dict) and i.get('kind') == 'bid']
    reviews_path = os.path.join(a.run, 'reviews.json')
    if a.no_reviews is not None:
        if not a.no_reviews.strip():
            sys.exit('--no-reviews needs the reason the dashboard decisions are not read (it is shown on every row). '
                     'Nothing planned.')
    elif os.path.exists(reviews_path):
        problem = saved_reviews_problem(reviews_path, a.asin, review_date)
        if problem:
            sys.exit(f'{problem}. Nothing planned.')
    elif bids:
        sys.exit(f'Save the dashboard decisions first: python scripts/dashboard.py reviews --asin {a.asin} --save {reviews_path}\n'
                 f'(the product file holds the bids item {", ".join(map(str, bids))}, whose decisions this plan must see; '
                 'when the dashboard can\'t be read, plan with --no-reviews "<why>" and every change goes to a person). '
                 'Nothing planned.')
    # a fetch request from an earlier pass is answered or still open: this pass writes it again if it is still open, so
    # one left over from a pass whose fetch was done no longer reads as an open fetch (2026-11-04, the top-15 re-runs)
    for stale in FETCH_REQUESTS:
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(a.run, stale))
    # the For Growth inputs, read before anything is planned: a file for another ASIN stops the run here
    listing, clicks = load_listing(a.run, a.asin), load_clicks_daily(a.run, a.asin)
    out = build(a.asin, cfg, shared, a.run, a.mode, a.today, with_lanes=False, allow_volatile=a.allow_volatile,
                partial_inventory=a.partial_inventory.strip() if a.partial_inventory else None)
    if ref is not None:
        out['summary'][0]['referral'] = ref
    cov = out['summary'][0].get('coverage')
    if cov is not None:
        write_json(os.path.join(a.run, 'coverage.json'), out.pop('coverage', None), indent=1)
        cov_cfg = shared.get('coverage') or {}
        # a required read missing is a fetch, not a choice (decision 191): no flag plans past it, exit 2 like the other
        # fetch requests, and nothing is planned, so no payload can go out without the Sponsored Brands bids
        required = coverage.required_stop(coverage.required_missing(cov, cov_cfg.get('required_reads')))
        if required:
            print(f'{required}. Nothing planned.', file=sys.stderr)
            sys.exit(2)
        problem = (coverage.stop_reason(cov, bool(cov_cfg.get('stop_on_missing_reads'))) if cov_cfg.get('stop_on_unowned')
                   else None)
        if problem and not (a.accept_unowned or '').strip():
            sys.exit(f'{problem}. Nothing planned.')
        if problem:
            cov['accepted'] = a.accept_unowned.strip()
    generated = propose_human_review(out, cfg, shared, review_date)
    manual_path = os.path.join(a.run, 'human_review.json')
    manual = validate_human_review(load_raw(manual_path)) if os.path.exists(manual_path) else []
    overrides = {item['id']: item for item in generated}
    overrides.update({item['id']: dict(item, origin='llm_review') for item in manual})
    market_path = os.path.join(a.run, 'market_review.json')
    research = load_raw(market_path) if os.path.exists(market_path) else None
    out['human_review'] = market_review.assess(list(overrides.values()), out, cfg, shared, review_date, research)
    if shared['placement'].get('recommendations', {}).get('enabled'):
        snapshot = placement_review.read_inputs(a.run, a.asin)
        if snapshot:
            placement_review.hold_defaults(out['changes'], snapshot['campaigns'], shared['placement'])
            # the placements may have moved: the campaign-wide values again, with the owners already invested as planned
            stamp_business_campaigns(out['changes'], out.get('business_live_invests'))
            placement_review.refresh_forecast(out, cfg, shared)
        placement_review.attach(out, cfg, shared, a.run, review_date)
    # section 6, after the placement refresh re-priced the re-rank. The lanes judge SQP age, onboarding and lock expiry on
    # the same SGT date the bids item id and the lock dates use, never on the machine's own date.
    inputs = load_lane_inputs(a.run)
    if a.no_reviews is not None:  # the decisions weren't read: none of the saved file, and nothing goes out on its own
        inputs.update(reviews=None, no_reviews=a.no_reviews.strip())
    # the AI program's planned invest, for the run summary: information only (decision 99), never a gate
    inputs['program'] = autonomy.program_month(data_dir, a.asin, shared)
    plan_lanes.assign(out, cfg, shared, a.mode, inputs, review_date)
    # the product-page base bid (placement_shape.py, decision 140): after the lanes, on the campaigns whose every bid row
    # applies on its own this run
    placement_shape.apply(out, cfg, shared, placement_review.read_inputs(a.run, a.asin), review_date)
    # the date this run's bids item id carries: dashboard.py's publish passes it to human_review.merge, so a run with
    # nothing to decide still supersedes the older runs' items
    out['summary'][0]['review_date'] = review_date
    # the For Growth item (plan_growth), beside the Bids item and out of the research gate (market_review.assess ran
    # above), planned after the lanes so its offer rows read this run's final bids. growth.json is written on every run
    item, out['growth_run'] = plan_growth(out, cfg, shared, a.asin, listing, clicks, review_date)
    out['summary'][0]['growth_trigger'] = out['growth_run']['trigger']
    if item is not None:
        out['human_review'] = validate_human_review(
            [i for i in out['human_review'] if i.get('id') != growth.GROWTH_ID] + [item])
        if out['growth_run']['item'] is not None:   # growth.json carries the item as plan.json does
            out['growth_run']['item'] = next(i for i in out['human_review'] if i['id'] == growth.GROWTH_ID)
    # the run's "Bids" item for Needs human, built from this plan's rows (never from a live dashboard read)
    bids = propose_bids(out, review_date)
    if bids is not None:
        out['human_review'] = validate_human_review(out['human_review'] + [bids])
    plan_path, written = write_outputs(a.run, out, shared, a.asin)
    s = out['summary'][0]
    print(json.dumps(dict(plan=plan_path, summary=s, harvest=out['harvest'], payloads=written,
                          skipped_negatives=len(out['skipped_negatives']), checks=len(out['checks'])), indent=1, default=str))


if __name__ == '__main__':
    main()
