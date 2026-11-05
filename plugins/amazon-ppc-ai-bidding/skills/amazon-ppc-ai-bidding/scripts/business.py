"""The planner's Amazon Business (B2B) sections (rulebook section 9; the design and its rulings in
docs/superpowers/specs/2026-10-21-b2b-lane-and-roles-design.md).

The team's Amazon-Business-exclusive campaigns are a shopper kind of their own: their keywords are priced on the B2B
campaigns' own evidence, with one owner per search inside the kind and the invests made inside the team's B2B campaigns.
plan.build() plans the consumer kind and calls these where its business sections used to stand, in this order:

  pool, records        section 1c: the B2B pool (B2B_CVR) and the business search records (business_terms)
  owners_and_homes     the business owner of each business invest search, and where a new business exact keyword goes
  bid_pull             Amazon's suggestions read in a B2B ad group, and the business exit 2 (after the consumer need file)
  price                section 2, inside the keyword loop: a business keyword's price off the invest path
  promotion_rows       section 3: the Business invest rows (returns business_live)
  new_keyword_rows     section 3: the business New exact keyword rows, then the campaigns holding a business invest
  scale_insights_row   section 3: the B2B Scale Insights rules row, before the pauses and the funnel negatives
  funnel_negatives     section 3: the funnel negatives inside the business kind, after the consumer ones
  stop_loss            the business stop-loss step-downs (stop_loss.py), or a review where none can be written, after
                       the consumer ones
  stamp_campaigns      after placement_review.hold_defaults (plan.main() runs it again after its placement refresh)
  rerank_rows          section 5: the business re-rank rows, after the consumer ones
  summary              summary.business

campaign_rows is read by stamp_campaigns and plan.payload_entries; plan.py keeps the two under the names they had there
(business_campaign_rows, stamp_business_campaigns).

ctx is one types.SimpleNamespace: build() fills it after the consumer search roles (section 1) with the run's inputs and
adds the names each later section needs just before its call. Each function's docstring lists the names it reads and the
ones it sets. The planner's own helpers (role_ladder, add, invest_budget, live_budget_tos, num, evidence_text,
funnel_negatives, ...) come through ctx or as arguments: plan imports this module, so this module never imports plan. Nothing
here writes to Amazon.
"""
import datetime as dt
import math
import os
import re
import sys
import types
from collections import Counter, defaultdict

import budget_headroom
import evidence
import stop_loss as stop_loss_rows
from searchtext import norm


# ----------------------------------------------------------------------------- 1c. the business search records
def keyword_rows(kw_rows, family):
    """The keyword rows of the product's B2B campaigns (family Business): the pool's, the records' and the owners'. build
    reads them once (its b2b_rows, ctx.b2b_rows)."""
    return [m for m in kw_rows if family(m.get('CampaignName')) == 'Business']


def pool(b2b_rows, prior_cvr, prior_clicks, num):
    """The B2B pool (build's B2B_CVR; design 4a): the business keyword rows' (keyword_rows) 90-day orders and clicks,
    shrunk by prior_clicks (the 10-click prior) toward prior_cvr, the account's B2B conversion from config
    (business.pool_prior_cvr), else the product's consumer ad conversion. num is plan.num, passed in because plan imports
    this module."""
    return ((sum(num(m.get('Orders')) for m in b2b_rows) + prior_clicks * prior_cvr) /
            (sum(num(m.get('Clicks')) for m in b2b_rows) + prior_clicks))


def records(ctx):
    """The business search records (build's business_terms; design 4a): the role ladder (ctx.role_ladder) run with
    owner_kind='business' on the B2B campaigns' own search-term rows, for every search they have rows for or a business
    keyword holds, each shrunk toward the B2B pool. A seasonal product's would-be Rank records bid as Defend.

    Reads ctx: ST_B, NO_ROWS, b2b_rows, sq, role_ladder, irrelevant, B2B_CVR, season_now. Sets nothing; returns
    {search: record}."""
    ST_B, NO_ROWS, sq, role_ladder, irrelevant = ctx.ST_B, ctx.NO_ROWS, ctx.sq, ctx.role_ladder, ctx.irrelevant
    B2B_CVR, season_now = ctx.B2B_CVR, ctx.season_now
    b2b_rows = ctx.b2b_rows
    business_terms = {}
    for t in sorted(set(ST_B) | {norm(m.get('Keyword')) for m in b2b_rows}):
        if t:
            business_terms[t] = role_ladder(t, sq.get(t), ST_B.get(t, NO_ROWS), B2B_CVR, irrelevant, owner_kind='business')
    # a seasonal product invests in no business search in any phase: its season rank searches are consumer invests, and in
    # wake and harvest nothing is invested in (section 1b; spec 9b, ruling 4). A business search that would be
    # Rank bids as Defend, at its breakeven, so the season never stops the run for a business bid pull
    if season_now:
        for r in business_terms.values():
            if r['role'] == 'Rank':
                r.update(role='Defend', sub_role='Defend', season_defend=True,
                         why=f"{season_now['phase']}: a seasonal product invests in no business search, its breakeven "
                             f"bid; {r['why']}")
    return business_terms


# ----------------------------------------------------------------------------- owners and homes
def id_order(x):
    """Amazon ids compare as numbers (the lower campaign id is the older campaign); anything else sorts after them."""
    s = str(x or '')
    return (0, int(s), '') if s.isdigit() else (1, 0, s)


def owners_and_homes(ctx):
    """The business owner of each business invest search, and where a new business exact keyword goes (design 4c;
    rulebook 9.3). Returns a SimpleNamespace:
      owner_by_search  {search: keyword row}, its owner keyword (build's business_owner)
      business_exact   the business invest searches a B2B exact keyword already holds (in a campaign not archived)
      homes            the B2B exact campaigns a new exact keyword may go into
      home             the one it goes into (build's new_keyword_home), or None
      home_ad_group    campaign id -> the ad group a new exact keyword goes into there, or None
      bid_group        search -> where its business suggestion is read (build's business_bid_group)
      unread_b2b       the B2B campaigns the keyword report names that campaigns.json lacks (ruling 18)
      serves           campaign id -> whether the planner may invest in it
      marker           business.exact_campaign_marker

    Reads ctx: camps, kw_rows, b2b_rows, kind, st_rows, business_terms, biz_cfg, num. Sets nothing."""
    camps, kw_rows, kind, st_rows, num = ctx.camps, ctx.kw_rows, ctx.kind, ctx.st_rows, ctx.num
    business_terms, biz_cfg = ctx.business_terms, ctx.biz_cfg
    b2b_rows = ctx.b2b_rows
    camp_by_id = {str(c.get('campaignId')): c for c in camps}
    # the B2B campaigns the keyword report names that campaigns.json lacks (the file not read, or the campaign missing
    # from it): each counts as a campaign "not read live" (spec 9b, ruling 18). It can be a new business keyword's home and
    # is in the Scale Insights row, with its id from the keyword rows, and no budget is ever written to it (ruling 7: no
    # live budget to compare with)
    camp_names = {c.get('name') for c in camps}
    unread_b2b = {}
    for m in kw_rows:
        cid, cname = str(m.get('CampaignId') or ''), m.get('CampaignName') or ''
        if cid and cname and cid not in camp_by_id and cname not in camp_names and kind(cname) == 'business':
            unread_b2b.setdefault(cid, dict(campaignId=cid, name=cname))
    unread_b2b = list(unread_b2b.values())

    def serves(cid):
        """A campaign the planner may invest in: enabled in the campaign list, or not in it (the keyword report is the
        only record; the live checks read it before the apply). A paused or archived campaign never takes an invest."""
        c = camp_by_id.get(str(cid))
        return c is None or (c.get('state') or 'ENABLED').upper() == 'ENABLED'

    # the business owner of each business invest search (design 4c; rulebook section 3 inside the kind): its enabled B2B
    # exact keyword with the most 90-day clicks, ties to the lower campaign id. Enabled: not held by the live inventory
    # (stale, or the target, ad group or campaign not enabled) and in a campaign that serves. The other B2B exact keywords of
    # the search are its copies, paused only while the owner invests (build's keyword loop). Consumer keywords are never its
    # copies, nor it theirs: each kind's owner is chosen on its own campaigns
    business_owner = {}
    business_exact = set()   # business invest searches a B2B exact keyword already holds (in a campaign not archived)
    for m in b2b_rows:
        t = norm(m.get('Keyword'))
        if t not in business_terms or business_terms[t]['role'] != 'Rank' or (m.get('MatchType') or '').lower() != 'exact':
            continue
        if ((camp_by_id.get(str(m.get('CampaignId'))) or {}).get('state') or '').upper() != 'ARCHIVED':
            business_exact.add(t)
        if m.get('inventory_hold') or not serves(m.get('CampaignId')):
            continue
        key = (-num(m.get('Clicks')), id_order(m.get('CampaignId')), id_order(m.get('KeywordId')))
        if t not in business_owner or key < business_owner[t][0]:
            business_owner[t] = (key, m)
    business_owner = {t: m for t, (_, m) in business_owner.items()}

    # a business invest search no B2B exact keyword holds gets one added to a campaign a person built (design 4c; the
    # planner never creates a business campaign, MarketplaceAdPros can't): the B2B exact campaign named with
    # business.exact_campaign_marker ("B2B - Search Terms with Sales - Exact") that already holds the most business owners,
    # else the lowest-numbered one. Never a Launch Targets campaign: the team's Launch Targets strategy negates a search in
    # that ad group once it has an order, and an invest search has orders by definition. A marker campaign the keyword
    # report names but campaigns.json lacks is a home too, not read live (unread_b2b, ruling 18)
    marker = biz_cfg.get('exact_campaign_marker')
    owners_in = Counter(str(m.get('CampaignId')) for m in business_owner.values())

    def campaign_number(name):
        found = re.search(r'(\d+)\s*$', name or '')
        return int(found.group(1)) if found else math.inf

    homes = [c for c in camps + unread_b2b if marker and marker in (c.get('name') or '') and kind(c.get('name')) == 'business'
             and serves(c.get('campaignId'))]
    new_keyword_home = min(homes, default=None, key=lambda c: (-owners_in[str(c.get('campaignId'))],
                                                                campaign_number(c.get('name')), id_order(c.get('campaignId'))))

    def home_ad_group(cid):
        """The ad group a new business exact keyword goes into: the one of the campaign's keyword rows with the most clicks
        (a team's B2B exact campaign has one ad group). None when no keyword row of the campaign was read."""
        rows = [m for m in kw_rows if str(m.get('CampaignId')) == cid and m.get('AdGroupId')]
        return str(min(rows, key=lambda m: (-num(m.get('Clicks')), id_order(m.get('AdGroupId'))))['AdGroupId']) if rows else None

    def business_bid_group(t):
        """Where Amazon's suggestion for a business invest search is read (design 4h): the owner keyword's ad group, else the
        ad group its new exact keyword goes into (design 4c). With neither (no B2B exact campaign to add it to), the B2B
        keyword or search-term row that paid most for the search, so a person still has a B2B ad group to read it in."""
        m = business_owner.get(t)
        if not m and new_keyword_home:
            cid = str(new_keyword_home.get('campaignId'))
            ag = home_ad_group(cid)
            if ag:
                return dict(search=t, campaign_id=cid, ad_group_id=ag)
        if not m:
            paid = ([m for m in b2b_rows if norm(m.get('Keyword')) == t] or
                    [m for m in st_rows if norm(m.get('SearchTerm')) == t and kind(m.get('CampaignName')) == 'business'])
            m = max(paid, key=lambda m: num(m.get('Spend'))) if paid else {}
        return dict(search=t, campaign_id=str(m['CampaignId']) if m.get('CampaignId') else None,
                    ad_group_id=str(m['AdGroupId']) if m.get('AdGroupId') else None)

    return types.SimpleNamespace(owner_by_search=business_owner, business_exact=business_exact, homes=homes,
                                 home=new_keyword_home, home_ad_group=home_ad_group, bid_group=business_bid_group,
                                 unread_b2b=unread_b2b, serves=serves, marker=marker)


# ----------------------------------------------------------------------------- the business bid pull
def bid_pull(ctx, run):
    """Amazon's suggested bids for the business invest searches (design 4h): suggested_bids_business.json, read in each
    search's own B2B ad group. When a search a row will price has none, need_suggested_bids_business.json names the ad
    group to read it in and the run exits 2. build() writes the consumer need_suggested_bids.json before this and exits 2
    after it for the consumer searches, so one pull answers both.

    Once Amazon was tried (ctx.bids_tried, bid_sources_tried.json; decision 106) a search still without one doesn't stop the
    run: it takes the no-suggestion bid at its B2B breakeven, as a consumer figure never prices a B2B auction, and is listed
    in ctx.business_fallback.

    Reads ctx: asin, business_rank_terms, owners (owner_by_search, business_exact, bid_group), load_suggested, write_json,
    bids_tried. Sets ctx: sug_b ({search: [low, median, high]}), business_fallback (the searches priced without one)."""
    # business invest searches: Amazon's suggestion read in their own B2B ad group (design 4h), never the consumer one
    sug_b = ctx.sug_b = ctx.load_suggested(run, 'suggested_bids_business.json')
    asin, business_rank_terms, write_json = ctx.asin, ctx.business_rank_terms, ctx.write_json
    business_owner, business_exact = ctx.owners.owner_by_search, ctx.owners.business_exact
    business_bid_group = ctx.owners.bid_group
    # a business invest search needs Amazon's suggestion read in its own B2B ad group (design 4h): a B2B auction prices
    # differently (B2B clicks $1.63 against $0.87 consumer, 90 days to 2026-10-21), so a consumer suggestion never stands
    # in. Asked for alongside the consumer ones, so one pull covers both; only for the searches a row will price (an owner
    # that invests, or a new exact keyword), so a search whose exact keyword can't take the invest never stops the run
    missing_b = [t for t in business_rank_terms if t not in sug_b and (t in business_owner or t not in business_exact)]
    ctx.business_fallback = []
    if missing_b and getattr(ctx, 'bids_tried', None) is not None:
        ctx.business_fallback = sorted(missing_b)
        return
    if missing_b:
        write_json(os.path.join(run, 'need_suggested_bids_business.json'),
                   dict(asin=asin, searches=[business_bid_group(t) for t in missing_b],
                        how='MAP get_amazon_ads_ad_group_bid_recs in the named B2B ad group, or any enabled B2B ad group of '
                            'the product when none is named, keywords [{text, match_type: EXACT}]; save as '
                            'suggested_bids_business.json {search: [low, median, high]}, then rerun.'), indent=1)
        print(f'{len(missing_b)} business invest searches need Amazon suggested bids from their B2B ad group first: '
              f'see need_suggested_bids_business.json')
        sys.exit(2)


# ----------------------------------------------------------------------------- business keyword prices
def price(ctx, role, idx_b, clk, od, be, hi):
    """A business keyword's role, action and bid off the invest path (design 4b, with phase 1's guards on its own index,
    design 4g): its own index pauses it below 0.5 on 30+ of its own clicks; a Hold or Defend record holds it at its
    breakeven; a Trim record trims it, and so does its own index below 0.8 on 15+ clicks where the record can't judge it;
    anything else (Test, Leave, Discovery, or an invest search's copy no owner invests from: role Rank) holds at its
    breakeven, capped at the B2B average until it has 3 orders. hi, the business suggested high, bounds the bid. Every
    breakeven here is taken at the non-rank share, ctx.nr (config non_rank_bid_factor: 1 since decision 157, 0.85 under decision 139; 1 in season); Trim stays 70%.

    Reads ctx: th, PROFIT, B2B_CVR, nr. Sets nothing; returns (role, action, new bid), the role as the row carries it."""
    th, PROFIT, B2B_CVR = ctx.th, ctx.PROFIT, ctx.B2B_CVR
    nr = getattr(ctx, 'nr', 1.0)
    at = 'breakeven' if nr == 1 else f'{nr:.0%} of breakeven'
    if idx_b is not None and idx_b < th['index_pause'] and clk >= th['pause_min_clicks']:
        return 'Trim', 'Pause: trails the market badly on 30+ clicks (business)', 0
    if role in ('Hold', 'Defend'):
        role, action, new = role, f'Hold at {at} (business)', round(be * nr, 2)
    elif role == 'Trim' or (idx_b is not None and idx_b < th['index_hold'] and clk >= th['trim_min_clicks']):
        role, action, new = 'Trim', 'Trim to 70% of breakeven (business)', round(max(th['trim_min_bid'], th['trim_factor'] * be), 2)
    else:
        role = 'Hold' if role == 'Rank' else role
        new = round((be if od >= 3 else min(be, PROFIT * B2B_CVR)) * nr, 2)
        action = (f'Hold at {at} (business)' if od >= 3 else
                  f'Hold at {at} (business, capped at the B2B average until 3 orders)')
    return role, action, (round(min(new, hi), 2) if hi else new)


# ----------------------------------------------------------------------------- the business invests
# a Business invest or business New exact keyword row whose campaign was not read live: its how says so
BUDGET_UNREAD = (' The campaign was not read live (campaigns.json), so its budget is left out of the update: check the '
                 'live budget before any change.')


def promotion_rows(ctx, add):
    """The Business invest rows (design 4b; rulebook 9.3, 9.5): one per business owner keyword that invests, carrying its
    bid, its campaign's budget and its top of search together. Returns business_live: the owners already invested as
    planned, which write no row.

    Reads ctx: plan, business_terms, live_budget_tos, invest_budget, evidence_text, business_why.
    Sets ctx: business_owned, {business invest search: the campaign that holds (or will hold) its owner keyword}, which
    new_keyword_rows adds to."""
    plan, business_terms, live_budget_tos, invest_budget = ctx.plan, ctx.business_terms, ctx.live_budget_tos, ctx.invest_budget
    evidence_text, business_why = ctx.evidence_text, ctx.business_why
    # the business invests (design 4b): one Business invest row per owner keyword, inside the team's B2B campaign that
    # holds it (people build the B2B campaigns; MarketplaceAdPros can't). Like a consumer promotion it carries the bid, the
    # campaign's budget and its top of search together, and it is the whole change: no Bid change or Budget and top of
    # search row for the owner. No row when all three are already as planned (as a Bid change at its price). Its copies
    # pause in build, its funnel negatives stay inside the business kind (after the consumer ones). The campaign-wide top of
    # search and budget are stamped on every row of a campaign once the placements are settled (stamp_campaigns),
    # counting the owners already invested as planned too (business_live: they write no row, but their campaign's top of
    # search and budget must not drop under them). A budget is never lowered: a campaign not read live has no budget to
    # compare with, so none is written
    business_owned = {}   # business invest search -> the campaign that holds (or will hold) its owner keyword
    business_live = []    # the business owners already invested as planned: no row, but they count in their campaign's update
    for p in plan:
        if p.get('owner_kind') != 'business' or p['role'] != 'Rank' or not p['action'].startswith(('Invest', 'Prove')):
            continue
        t, sub, cid = norm(p['keyword']), p['sub_role'], p['campaign_id']
        business_owned[t] = cid
        lo, med, hi = p['suggested']
        b0, t0, others = live_budget_tos(cid)
        budget = max(b0 or 0, invest_budget(t, sub))   # never lower than the campaign's live budget
        current = round(p['bid'], 2) if p['bid'] is not None else None
        if current == p['new_bid'] and budget == b0 and p['tos_pct'] == t0:
            business_live.append(dict(keyword=t, role=sub, campaign_id=cid, tos=p['tos_pct'], budget=budget))
            continue
        r = business_terms[t]
        add(step=3, type='Business invest', keyword=t, match='exact', role=sub, campaign=p['campaign'], campaign_id=cid,
            ad_group_id=p['ad_group_id'], keyword_id=p['keyword_id'], current=current, new=p['new_bid'], tos=p['tos_pct'],
            tos_bid=round(p['new_bid'] * (1 + p['tos_pct'] / 100), 2), tos_now=t0, other_placements=others, budget=budget,
            budget_now=b0, sug_low=lo, sug_median=med, sug_high=hi, clicks90=p['clicks90'], orders90=p['orders90'],
            spend90=p['spend90'], cvr=p['cvr_used'], breakeven=p['breakeven_cpc'], baseline_cvr=p['baseline_cvr'],
            prior_cvr=p['prior_cvr'], owner_kind='business', evidence=evidence_text(r),
            why=(f"{business_why(p['prior_cvr'], t, role=False)} Beats the market on its own B2B clicks: index {r['index']:.2f} "
                 f"on {r['ad_clicks']} B2B clicks, {r['ad_orders']} orders. Bid: Amazon's suggested median read in a B2B ad "
                 f"group, or breakeven if higher, never above the high."),
            how='MAP update sp_keywords bid; sp_campaigns budget + complete placements (top of search to the standing policy); '
                'check the ad group for self-blocking negatives (references/live-checks.md)' + (BUDGET_UNREAD if b0 is None else ''))
    ctx.business_owned = business_owned
    return business_live


def new_keyword_rows(ctx, add):
    """The business New exact keyword rows (design 4c; rulebook 9.3): a business invest search no B2B exact keyword holds
    gets one added to the team's B2B exact campaign (owners_and_homes' home), at the invest bid, with the campaign update
    a Business invest row carries. Then the B2B campaigns that hold a business invest this run.

    Reads ctx: business_rank_terms, business_terms, owners (business_exact, home, home_ad_group, marker), sug_b,
    invest_bid_for, invest_budget, live_budget_tos, plc, B2B_CVR, evidence_text, business_why, business_live,
    changes. Adds to ctx.business_owned. Sets ctx: business_invested, {campaign id: the business invest searches it holds}."""
    business_rank_terms, business_terms, sug_b, plc, B2B_CVR = (ctx.business_rank_terms, ctx.business_terms, ctx.sug_b,
                                                                ctx.plc, ctx.B2B_CVR)
    business_exact, new_keyword_home = ctx.owners.business_exact, ctx.owners.home
    home_ad_group, marker = ctx.owners.home_ad_group, ctx.owners.marker
    invest_bid_for, invest_budget, live_budget_tos = ctx.invest_bid_for, ctx.invest_budget, ctx.live_budget_tos
    evidence_text, business_why = ctx.evidence_text, ctx.business_why
    business_owned, business_live, changes = ctx.business_owned, ctx.business_live, ctx.changes
    # a business invest search no B2B exact keyword holds (it converts through the B2B phrase or broad campaigns): the exact
    # keyword is added to the product's B2B exact campaign (owners_and_homes), at the invest bid, with the campaign update a
    # Business invest row carries. Always a person's call. Without an ad group id (no keyword row of that campaign read) or
    # without such a campaign, the row says what to do first and carries no payload. A search whose B2B exact keyword can't
    # take the invest (held by the live inventory, or in a paused campaign) gets none: it has its keyword already
    for t in business_rank_terms:
        if t in business_exact:
            continue
        r = business_terms[t]
        sub = r['sub_role']
        lo, med, hi = tuple(sug_b.get(t) or (None, None, None))
        new, src = invest_bid_for(lo, med, hi, r['be_cpc'])
        tos = plc['prove_tos_pct'] if sub == 'Prove first' else plc['invest_tos_pct']
        home = new_keyword_home or {}
        cid = str(home['campaignId']) if home.get('campaignId') else None
        ag = home_ad_group(cid) if cid else None
        b0, t0, others = live_budget_tos(cid) if cid else (None, None, [])
        if ag:
            business_owned[t] = cid
        negs = f'check the ad group\'s negatives for "{t}" (references/live-checks.md): a negative exact there blocks the new keyword'
        if ag:
            how = (f'MAP create sp_keywords (exact, at the invest bid, ENABLED) in ad group {ag}; sp_campaigns budget + complete '
                   f'placements (top of search to the standing policy). First {negs}' + (BUDGET_UNREAD if b0 is None else ''))
        elif cid:
            how = (f'No keyword row of this campaign was read, so its ad group is unknown: MAP list_resources sp_ad_groups '
                   f'campaign_id={cid} first, {negs}, then add the keyword. No payload until then')
        else:
            # neither campaigns.json nor the keyword report names one (ruling 18): the file may not have been read, so a
            # person looks before building a campaign that may exist
            how = (f'No enabled B2B campaign named "{marker}" in campaigns.json (not read, or none exists): check the Ads '
                   f'console before building one (MarketplaceAdPros cannot build an Amazon Business campaign), then the next '
                   f'run adds the keyword; {negs}. No payload')
        add(step=3, type='New exact keyword', keyword=t, match='exact', role=sub, campaign=home.get('name'), campaign_id=cid,
            ad_group_id=ag, current=None, new=new, tos=tos, tos_bid=round(new * (1 + tos / 100), 2), tos_now=t0,
            other_placements=others, budget=max(b0 or 0, invest_budget(t, sub)), budget_now=b0, sug_low=lo, sug_median=med,
            sug_high=hi, source=src, baseline_cvr=round(B2B_CVR, 4), prior_cvr=r['cvr_est'], owner_kind='business',
            evidence=evidence_text(r),
            why=(f"{business_why(r['cvr_est'], t, role=False)} Beats the market on its own B2B clicks (index {r['index']:.2f} "
                 f"on {r['ad_clicks']} B2B clicks, {r['ad_orders']} orders) through the B2B phrase or broad campaigns, and no "
                 f"B2B exact keyword holds it: add one to the team's B2B exact "
                 f"campaign at Amazon's suggested median read in a B2B ad group, or breakeven if higher, never above the high."),
            how=how)
    # the B2B campaigns that hold a business invest this run (design 4e, 4h): a Business invest row's, a business New exact
    # keyword's, and an owner already invested as planned (business_live: no row, but its campaign runs the invest's budget
    # and top of search). The budget steps leave them out, and in Scale Insights they go to the exact-owners strategy
    business_invested = defaultdict(set)   # campaign id -> the business invest searches it holds
    for x in business_live + [c for c in changes if c.get('owner_kind') == 'business'
                              and c['type'] in ('Business invest', 'New exact keyword')]:
        if x.get('campaign_id'):
            business_invested[str(x['campaign_id'])].add(x['keyword'])
    ctx.business_invested = business_invested


# ----------------------------------------------------------------------------- Scale Insights
def scale_insights_row(ctx, add):
    """The Scale Insights rules row for the B2B ad groups (design 4h; rulebook 9.7): their bid rules come off until the
    product file records the date (business.si_rules_off), and after that a campaign that newly holds a business invest
    moves to the exact-owners strategy until business.si_exact_owners lists it (spec 9b, ruling 17).

    Reads ctx: camps, kind, owners (unread_b2b), cfg, shared, business_invested. Sets nothing."""
    camps, kind, cfg, shared = ctx.camps, ctx.kind, ctx.cfg, ctx.shared
    unread_b2b, business_invested = ctx.owners.unread_b2b, ctx.business_invested
    # Scale Insights for the B2B ad groups (design 4h; SKILL.md rule 1, one bid owner per product): the planner prices the
    # B2B keywords now, so the team's B2B strategies come off, or their nightly bid rules move the AI's business bids back
    # within a day and the Launch Targets rule negates the searches that convert. Like the onboarding row it is done in the
    # web app (the MCP can't change assignments) and always a person's call; every run carries it until the product file
    # records the date it was done (business.si_rules_off), and a decline locks it like any row. Its own keyword gives it a
    # row id apart from the onboarding row's. An archived campaign never serves again, so it is left out. The campaigns are
    # campaigns.json's and the B2B campaigns the keyword report names that it lacks (unread_b2b, ruling 18), with their ids
    # from either source, so a campaign list not read never hides the row.
    # After the rules came off, a campaign that newly holds a business invest still has to move to the exact-owners strategy
    # with its searches whitelisted (spec 9b, ruling 17): the product file's business.si_exact_owners lists the campaign ids
    # already on it, and the row comes back for the campaigns holding a business invest that it does not list, naming only
    # those campaigns and their searches
    b2b_camps = sorted([c for c in camps if kind(c.get('name')) == 'business' and (c.get('state') or '').upper() != 'ARCHIVED']
                       + unread_b2b, key=lambda c: c.get('name') or '')
    biz_file = cfg.get('business') or {}
    rules_off = biz_file.get('si_rules_off')
    on_103 = {str(c) for c in biz_file.get('si_exact_owners') or []}
    si_owner_camps = [c for c in b2b_camps if str(c.get('campaignId')) in business_invested]
    si_to_move = [c for c in si_owner_camps if str(c.get('campaignId')) not in on_103]
    if b2b_camps and (not rules_off or si_to_move):
        si = shared.get('scale_insights') or {}

        def strategy(key):
            """'103 / 302497': the strategy's number (its name starts with it) and its Scale Insights id, as onboarding.md
            names them."""
            sid = (si.get('strategies') or {}).get(key)
            number = ((si.get('names') or {}).get(str(sid)) or '').split(' ')[0]
            return f'{number} / {sid}' if number else str(sid)

        def whitelisted(cs):
            return ', '.join(sorted(set().union(*(business_invested[str(c.get('campaignId'))] for c in cs))))
        if rules_off:
            moving = si_to_move
            si_new = (f"Strategy {strategy('exact_skc_owner')} for the exact campaigns that newly own a business invest search "
                      f"({', '.join(c['name'] for c in moving)}), with those searches whitelisted ({whitelisted(moving)})")
            item = 'Move the B2B campaigns that newly hold a business invest to the exact-owners strategy'
            current = (f"The B2B bid rules came off on {rules_off}; these campaigns are not in business.si_exact_owners, so "
                       f"they still run the team's B2B strategy")
            then = ''
        else:
            moving = si_owner_camps
            si_others = [c['name'] for c in b2b_camps if str(c.get('campaignId')) not in business_invested]
            si_parts = []
            if moving:
                si_parts.append(f"Strategy {strategy('exact_skc_owner')} for the exact campaigns that own a business invest "
                                f"search ({', '.join(c['name'] for c in moving)}), with those searches whitelisted "
                                f"({whitelisted(moving)})")
            if si_others:
                si_parts.append(f"strategy {strategy('keyword_no_bid_rules')} for the {'other ' if moving else ''}B2B ad groups "
                                f"({', '.join(si_others)})")
            si_new = '; '.join(si_parts)
            item = 'Take the bid rules off the Amazon Business (B2B) ad groups of this product'
            current = "The team's B2B strategies (inch-up and target-ACOS rules; Launch Targets negates searches with orders)"
            then = 'set business.si_rules_off to the date'
        ids = sorted({str(c.get('campaignId')) for c in moving}, key=id_order)
        if ids:
            then += (' and ' if then else '') + f"add {', '.join(ids)} to business.si_exact_owners"
        add(step=1, type='Scale Insights rules', keyword='B2B ad groups', owner_kind='business', item=item, current=current,
            new=si_new[:1].upper() + si_new[1:],
            why="Scale Insights bid rules run every evening and would move the AI's business bids back within a day; the "
                "Launch Targets rule would negate the searches that convert.",
            how=f'Scale Insights web app (references/scale-insights-playbook.md); then {then} in the product file')


# ----------------------------------------------------------------------------- funnel negatives
def funnel_negatives(ctx, add, skipped):
    """The funnel negatives inside the business kind (design 4c; rulebook 9.3): a negative exact for each business invest
    search in every B2B ad group that paid for it in 90 days, other than its owner's campaign. Appends the ones it can't
    add to skipped (build's, shared with the consumer loop). The loop is plan.funnel_negatives, the consumer one's, run on
    the business kind with its own owner, exceptions and texts.

    Reads ctx: st_rows, kind, business_owned, B2B_WHY, funnel_negatives. Sets nothing."""
    st_rows, kind, business_owned, B2B_WHY = ctx.st_rows, ctx.kind, ctx.business_owned, ctx.B2B_WHY
    # funnel negatives inside the business kind (design 4c): every B2B ad group that paid for a business invest search in 90
    # days, other than the owner's campaign, gets a negative exact for it, with the consumer loop's two exceptions: never
    # inside a B2B exact campaign (another owner's, or one Amazon's close variants would switch off), never on a close
    # variant of a campaign's own exact keyword. Consumer ad groups never get one for a business invest (each kind's run of
    # the loop sees its own campaigns only); a new exact keyword with no ad group yet gets none, so its search keeps its traffic
    ctx.funnel_negatives({t: {cid} for t, cid in business_owned.items()}, st_rows, 'business', kind, add, skipped,
                         why=f'{B2B_WHY} This B2B ad group paid for the search in the last 90 days; the business owner holds it from now on.',
                         exact_marker='Exact',
                         exact_why='inside a B2B exact campaign; Amazon close-variant matching makes this risky',
                         variant_why=lambda own: f'close variant of the B2B exact campaign\'s own keyword "{own}": a negative here would switch it off',
                         owner_kind='business')


# ----------------------------------------------------------------------------- stop-loss
def stop_loss(ctx, add, stop_rows):
    """The business stop-loss reviews (design 4f; rulebook 9.6): every search in the business invest log invested in for
    the stop-loss weeks is judged on its B2B keyword's own orders and ACOS; a review row when it hasn't earned its keep.
    Appends each search's check to stop_rows (build's, after the consumer ones).

    Since autonomous runs (2026-10-22) it writes the step-down itself where it can (stop_loss.py) and drops the search's
    business invest row and its place in business_live; a review row is left only where no owner keyword can be found.

    Reads ctx: cfg, season_now, today, stop_weeks, business_terms, plan, owners, changes, business_live, live_budget_tos.
    Changes ctx.changes and ctx.business_live in place."""
    cfg, season_now, today, stop_weeks, business_terms = ctx.cfg, ctx.season_now, ctx.today, ctx.stop_weeks, ctx.business_terms
    # business stop-loss reviews (design 4f): a business invest is judged on what its B2B keyword earned, never on Rank Radar
    # (nobody knows whether a business account's purchase moves organic rank), and build's consumer review never judges
    # one. After the same weeks, every search in the business invest log is compared with its baseline: it has earned its
    # keep when its B2B orders grew (orders now above orders_then; the 90-day windows overlap, so this is a proxy for orders
    # since the start) and its 90-day ACOS is at or under the product's breakeven ACOS (profit / price, as the budget steps
    # judge it). Both, or a review. Without a price (or unit profit) the breakeven is unknown, so orders alone decide, and the
    # why says so.
    # A harvest has no business invests, so no review (as in build's); its out['stop_loss'] rows carry owner_kind
    be_acos = budget_headroom.product_breakeven(cfg)
    for t, log in ({} if (season_now or {}).get('harvest') else (cfg.get('business_invest_log') or {})).items():
        t = norm(t)
        try:
            age = (today - dt.date.fromisoformat(log.get('since'))).days
        except (TypeError, ValueError):
            continue
        if age < 7 * stop_weeks[0]:
            continue
        bt = business_terms.get(t) or {}   # no B2B record now: no B2B click or keyword in 90 days, so no order either
        then, now = log.get('orders_then'), bt.get('ad_orders') or 0
        acos = bt['ad_spend'] / bt['ad_sales'] if bt.get('ad_sales') else None
        gains = []
        if then is not None and now > then:   # no baseline: growth can't be shown, so a person looks at it
            gains.append('B2B orders up')
        if acos is not None and be_acos is not None and acos <= be_acos:
            gains.append('ACOS at or under breakeven')
        stop_rows.append(dict(keyword=t, owner_kind='business', age_days=age, gains=gains, orders_then=then, orders_now=now,
                              acos_now=round(acos, 4) if acos is not None else None, breakeven_acos=be_acos))
        if len(gains) == (2 if be_acos is not None else 1):
            continue
        acos_text = f'{acos:.0%}' if acos is not None else 'unknown (no B2B sales)'
        against = (f'against the {be_acos:.0%} breakeven' if be_acos is not None else
                   '(the product file has no price and unit profit to give a breakeven ACOS: judged on orders alone)')
        then_text = 'not recorded' if then is None else then
        # autonomous runs (Kim, 2026-10-22, decision 98): the planner writes the step-down itself (stop_loss.py): the
        # business owner keyword back to its breakeven, and, when no other business invest is left in its campaign, top of
        # search back to 0% with the budget as live. A business invest row of the search this run is dropped (it would
        # invest again), and so is the search's place among the owners already invested as planned (business_live), so
        # their campaign update no longer holds the boost up for it
        reason = (f"invested in the B2B campaign for {age} days ({age // 7} weeks): B2B orders {then_text} -> {now}, ACOS "
                  f"{acos_text} {against}")
        owner_id = (getattr(ctx, 'owners', None) and ctx.owners.owner_by_search.get(t) or {}).get('KeywordId')
        owner = stop_loss_rows.owner_row(ctx.plan or [], t, business=True, keyword_id=owner_id)
        done = None
        if owner is not None:
            cid = str(owner['campaign_id'])
            # what this run planned only because the owner invests goes too: its copies' pauses (a copy pauses only while
            # its owner invests, design 4c) and the funnel negatives of the search in the other B2B ad groups
            ctx.changes[:] = [x for x in ctx.changes if not (
                x.get('owner_kind') == 'business' and norm(x.get('keyword') or '') == t
                and (x.get('type') in ('Business invest', 'New exact keyword', 'Negative exact')
                     or (x.get('type') == 'Pause keyword' and x.get('role') in ('Invest', 'Prove first'))))]
            if ctx.business_live is not None:
                ctx.business_live[:] = [x for x in ctx.business_live if norm(x.get('keyword') or '') != t]
            others = (any(x.get('type') == 'Business invest' and str(x.get('campaign_id')) == cid for x in ctx.changes)
                      or any(str(x.get('campaign_id')) == cid for x in ctx.business_live or []))
            done = stop_loss_rows.step_down(ctx.changes, add, t, owner, reason, ctx.live_budget_tos, budget_to=None,
                                       campaign=not others, owner_kind='business')
        stop_rows[-1]['step_down'] = done or 'review'
        if done is not None:
            continue
        # the campaign log_invest recorded, when it did: it names the campaign to step down and gives the row an id of its
        # own, apart from a consumer review of the same search (plan_lanes.row_id), so a decision on one never holds the other
        held_in = {'campaign_id': str(log['campaign_id'])} if log.get('campaign_id') else {}
        add(step=8, type='Stop-loss review', keyword=t, role=log.get('role') or 'Invest', current=None, new=None,
            owner_kind='business', **held_in,
            why=f"Invested in the B2B campaign for {age} days: orders {then_text} -> {now}, ACOS {acos_text} {against}. Step down "
                f"to Hold at its breakeven; when no invest keyword is left in the campaign, top of search back to 0% and the "
                f"budget as live. No step-down could be written: its B2B exact keyword isn't in this run's keyword report.",
            how='Held (Monitor): the next run tries the step-down again once it can be written (decision 107); it is then a MAP bid + campaign update, and log_invest.py records it')


# ----------------------------------------------------------------------------- business invest campaigns
CAMPAIGN_WIDE = ' Campaign-wide: '


def campaign_rows(changes):
    """{campaign id: [rows]} of the business invests that write a campaign update: every Business invest row, and every
    business New exact keyword row with its ad group (one without writes nothing)."""
    groups = defaultdict(list)
    for c in changes:
        if c.get('campaign_id') and (c['type'] == 'Business invest' or (c['type'] == 'New exact keyword'
                                                                        and c.get('owner_kind') == 'business' and c.get('ad_group_id'))):
            groups[str(c['campaign_id'])].append(c)
    return groups


def stamp_campaigns(changes, live=()):
    """The Business invest and business New exact keyword rows of one campaign are one group (spec 9b, ruling 6): each
    carries campaign_tos and campaign_budget, the highest top of search and the highest budget among the
    group's rows in the whole plan and the campaign's owners already invested as planned (`live`, build's
    out['business_live_invests']: they write no row, and their policy top of search and budget are what the campaign runs
    now). So the campaign update any subset of the rows writes (one approval round, one lane folder) is the same one, and
    a new invest never takes the campaign below one already live or planned (+50% beats +30%). campaign_budget is None when
    the campaign wasn't read live: with no live budget to compare with, none is written (a budget is never lowered, design
    4b). The why names the setting and the searches behind it. Run after placement_review.hold_defaults has settled each
    row's top of search (build, and main after its placement refresh); running it again gives the same rows."""
    live_in = defaultdict(list)
    for owner in live or ():
        live_in[str(owner['campaign_id'])].append(owner)
    for cid, rows in campaign_rows(changes).items():
        owners = live_in.get(cid, [])
        tos = [r['tos'] for r in owners + rows if r.get('tos') is not None]
        budgets = ([o['budget'] for o in owners if o.get('budget') is not None] +
                   [r['budget'] for r in rows if r.get('budget') is not None and r.get('budget_now') is not None])
        campaign_tos, campaign_budget = (max(tos) if tos else None), (max(budgets) if budgets else None)
        live_tos, live_budget = rows[0].get('tos_now'), rows[0].get('budget_now')
        if any(r.get('placement_hold') for r in rows) or campaign_tos is None:
            tos_text = 'top of search held as live' + (f' (+{live_tos:g}%)' if live_tos is not None else '') + ', see the placement note'
        else:
            who = ', '.join([f"{o['keyword']} {o['role']} (already live)" for o in owners] +
                            [f"{r['keyword']} {r['role']}" for r in rows])
            tos_text = (f'top of search +{campaign_tos:g}%' + (f' (live +{live_tos:g}%)' if live_tos is not None else '')
                        + f" for every keyword in it, the highest policy among this run's business invests in it: {who}")
        budget_text = (f'budget ${campaign_budget:g}/day (live ${live_budget:g})' if campaign_budget is not None
                       else 'budget not read live, so none is written')
        for r in rows:
            r['campaign_tos'], r['campaign_budget'] = campaign_tos, campaign_budget
            r['why'] = r['why'].split(CAMPAIGN_WIDE)[0] + f'{CAMPAIGN_WIDE}{tos_text}; {budget_text}.'


# ----------------------------------------------------------------------------- re-rank
def rerank_rows(ctx):
    """The business invests' re-rank rows (design 4d; spec 9b, rulings 11 and 15): one per business rank search with a
    Business invest or business New exact keyword row this run, priced on its search's B2B 90 days. Returns the rows; build
    adds them to its re-rank after the consumer ones.

    Reads ctx: changes, business_terms, biz_cfg, bud, PROFIT, name, asin. Sets nothing."""
    changes, business_terms, biz_cfg, bud = ctx.changes, ctx.business_terms, ctx.biz_cfg, ctx.bud
    PROFIT, name, asin = ctx.PROFIT, ctx.name, ctx.asin
    # the business invests (design 4d): a re-rank row for every business rank search with a Business invest or business New
    # exact keyword row this run, priced on its search's B2B 90 days and kept under its own key (owner_kind 'business',
    # plan_lanes.row_key), so its band and modelled spend never overwrite the consumer owner's. A Business invest spends what
    # its search spent across the B2B campaigns (90 days / 3), not the keyword alone, scaled by its bid (new / current), with
    # its orders scaled the same (spec 9b, ruling 15: the consumer record's search level, and it counts the phrase groups'
    # spend the within-kind negatives move to the owner); a new exact keyword takes business.new_keyword_spend_share of the
    # invest budget (invest_per_day x 30), its orders at the search's B2B orders per dollar, capped at what the search
    # earned a month across every B2B campaign (its 90-day B2B orders / 3: a new keyword can't earn more than the whole
    # search did; spec 9b, ruling 11). A row it can't price (no current bid, no share in config) gets none: the lanes then
    # send its promotion to a person. The summary's invest totals stay the consumer ones
    rerank = []
    share = biz_cfg.get('new_keyword_spend_share')
    for x in changes:
        if x.get('owner_kind') != 'business' or x['type'] not in ('Business invest', 'New exact keyword'):
            continue
        t = x['keyword']
        r = business_terms.get(t)
        if r is None or r['role'] != 'Rank' or x.get('new') is None:
            continue
        if x['type'] == 'New exact keyword':
            if not isinstance(share, (int, float)) or isinstance(share, bool):
                continue
            spend = bud['invest_per_day'] * 30 * share
            orders = min(spend * r['ad_orders'] / r['ad_spend'], r['ad_orders'] / 3) if r['ad_spend'] else 0.0
        else:
            if not x.get('current'):
                continue
            ratio = x['new'] / x['current']
            spend, orders = r['ad_spend'] / 3 * ratio, r['ad_orders'] / 3 * ratio
        bid, tos = x['new'], x.get('tos') or 0
        days = r['observed_days'] or 84
        rerank.append(dict(product=name, asin=asin, keyword=t, owner_kind='business', role=x.get('role'),
                           month_searches=round(evidence.monthly_searches(r['sqp_volume'], days) or 0),
                           month_clicks=round(r['ad_clicks'] * 30 / 90), our_click_share=None,
                           ad_spend_now=round(r['ad_spend'] / 3, 2), bid=bid, tos=tos,
                           cpc=round((bid + bid * (1 + tos / 100)) / 2, 2), budget=x.get('budget'), spend=round(spend),
                           orders=round(orders, 1), net=round(orders * PROFIT - spend), capped=False))
    return rerank


# ----------------------------------------------------------------------------- summary
def summary(ctx):
    """summary.business (build's business_out): what the run saw and planned for the B2B campaigns (spec section 6).

    Reads ctx: plan, changes, camps, kind, B2B_CVR, pool_prior_out, BUSINESS_COPY_PAUSE. Sets nothing."""
    plan, changes, camps, kind, B2B_CVR = ctx.plan, ctx.changes, ctx.camps, ctx.kind, ctx.B2B_CVR
    pool_prior_out, BUSINESS_COPY_PAUSE = ctx.pool_prior_out, ctx.BUSINESS_COPY_PAUSE
    biz_cnt = Counter(x['type'] for x in changes if x.get('owner_kind') == 'business')
    # campaigns: every business campaign the run saw, in the keyword report or the campaign list, less the archived ones
    archived = {c.get('name') for c in camps if (c.get('state') or '').upper() == 'ARCHIVED'}
    business_out = dict(campaigns=len({n for n in [p['campaign'] for p in plan] + [c.get('name') for c in camps]
                                       if kind(n) == 'business' and n not in archived}),
                        keywords=sum(1 for p in plan if p.get('owner_kind') == 'business'), pooled_cvr=round(B2B_CVR, 4),
                        bid_changes=biz_cnt['Bid change'], pauses=biz_cnt['Pause keyword'], pool_prior=pool_prior_out,
                        invest=sum(1 for x in changes if x['type'] == 'Business invest' and x['role'] == 'Invest'),
                        prove_first=sum(1 for x in changes if x['type'] == 'Business invest' and x['role'] == 'Prove first'),
                        copies_paused=sum(1 for p in plan if p.get('owner_kind') == 'business'
                                          and p['action'] == BUSINESS_COPY_PAUSE),
                        negatives=biz_cnt['Negative exact'], new_keywords=biz_cnt['New exact keyword'],
                        # spec section 6 (spec 9b, ruling 14): the business stop-loss reviews and the B2B Scale Insights row
                        stop_loss_reviews=biz_cnt['Stop-loss review'], si_rows=biz_cnt['Scale Insights rules'],
                        stop_loss_step_downs=len({x['keyword'] for x in changes if x.get('owner_kind') == 'business'
                                                  and x.get('stop_loss_step_down')}))
    return business_out
