"""The planner's lanes: every change gets auto, human or monitor, the bands, the split payloads and apply_after.

Each test builds a small synthetic run folder in a temp dir (3 SQP queries, 6 search-term rows, 8 keyword rows,
2 product targets, campaigns.json, suggested_bids.json) and plans it with build() and write_outputs(), or with main().
"""
import contextlib
import copy
import csv
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone

import human_review
import lanes
import plan as planner
import plan_lanes
import stage

UTC = timezone.utc
SKILL = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((SKILL / 'config.json').read_text(encoding='utf-8'))
ASIN = 'B0TEST0001'
TODAY = '2026-10-19'
NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)  # a Monday, 08:00 in Los Angeles
# The fixtures run on these settings, not on the live config, so retuning config.json doesn't break them.
# prove_index 1.25 since 2026-10-22 (was 1.4): Kim's bar for 2 orders is 1.25 everywhere (data-stage design 4.4)
AUTO = {'enabled': True, 'prove_orders': 2, 'prove_index': 1.25, 'invest_orders': 3, 'invest_index': 1.1,
        'raise_orders': 3, 'raise_index': 1.4, 'max_raise_pct': 25, 'min_opportunity': 300,
        'monitor_spend_cap': 15, 'max_raises': 20, 'max_loss_month': 60,
        'invest_guide_month': 2000,  # a guide, not a gate (decision 99; it replaced kim_product_month, $600)
        'lock_weeks': 4, 'big_cut_pct': 50, 'big_cut_orders': 3,
        'repromote_cooloff_days': 56}  # the re-investment cool-off after a stop-loss step-down (2026-10-22)
THRESHOLDS = {'prior_clicks': 10, 'market_prior_clicks': 20, 'trusted_min_clicks': 10, 'trusted_min_ad_orders': 3,
              'index_invest': 1.1, 'index_hold': 0.8, 'index_pause': 0.5, 'invest_min_volume': 150,
              'invest_min_purchases': 3, 'defend_impression_share': 0.1, 'defend_organic_share': 0.5,
              'trim_min_clicks': 15, 'pause_min_clicks': 30, 'trim_factor': 0.7, 'test_floor_bid': 0.35,
              'test_default_market_cvr': 0.1, 'leave_bid_cvr': 0.1, 'no_suggestion_multiplier': 1.5,
              'trim_min_bid': 0.1, 'stop_loss_weeks': [4, 6], 'stop_loss_months': [3, 6, 9, 12]}

STW = f'Cards - {ASIN} - Search terms w sales'
AUTO_CAMPAIGN = f'Cards - {ASIN} - Auto'
BROAD = f'Cards - {ASIN} - Broad'
LOW = f'Cards - {ASIN} - Low Bids'
SKC = f'Cards - {ASIN} - Exact SKC - thank you cards - TOS Rank'
PT = f'Cards - {ASIN} - Product Targets'
IDLE_SKC = f'Cards - {ASIN} - Exact SKC - note cards - TOS Rank'  # an idle exact campaign, reused by a promotion
IDS = {STW: ('101', '201'), AUTO_CAMPAIGN: ('102', '202'), BROAD: ('103', '203'), LOW: ('104', '204'),
       SKC: ('105', '205'), PT: ('106', '206'), IDLE_SKC: ('107', '207')}


@contextlib.contextmanager
def planned_at(now=NOW):
    """plan.py stamps apply_after from the machine's clock (the first US weekday). A test that runs plan.main() and then
    checks the write window pins that clock here, so it doesn't depend on the day it runs."""
    real = plan_lanes.assign

    def assign(out, cfg, shared, mode, inputs, today_iso=None, now_utc=None):
        return real(out, cfg, shared, mode, inputs, today_iso, now_utc or now)
    with unittest.mock.patch.object(plan_lanes, 'assign', assign):
        yield


def shared_config(**placement):
    s = copy.deepcopy(CONFIG)
    s['auto'] = dict(AUTO, enabled=False)
    s['thresholds'] = copy.deepcopy(THRESHOLDS)
    s['budgets'].update(invest_per_day=10, prove_per_day=5, rerank_click_share_target=0.1)
    s['placement'].update(invest_tos_pct=50, prove_tos_pct=30)
    s['placement']['recommendations']['enabled'] = placement.get('recommendations', True)
    # the standing rank top-of-search policy (Kim, 2026-10-20) is off unless a test asks for it: the other tests run on
    # the 0% start they were written for
    s['placement']['rank_tos_standing'] = dict(approved=bool(placement.get('standing', False)), by='Kim', on='2026-10-20')
    s['targets'].update(enabled=True, proven_orders=3, pause_min_clicks=22, skip_campaign_markers=['TOS'])
    # the Hold uplift test (decision 108) is off unless a test asks for it: the fixtures' Hold searches keep their breakeven
    s['hold_uplift'] = dict(s.get('hold_uplift') or {}, enabled=False)
    # the organic share, the top-10 rule and the leak check (decisions 143 and 175) are off unless a test asks for them:
    # the other tests run on the non-rank bids they were written for (test_organic_share.py turns them on)
    s['organic_share'] = dict(s.get('organic_share') or {}, enabled=bool(placement.get('organic', False)))
    # pricing on each search's SQP conversion (decision 162) is off unless a test asks for it: the other tests run on the
    # ad-record prices they were written for (test_sqp_pricing.py turns it on)
    s['pricing'] = dict(s.get('pricing') or {}, search_conversion=placement.get('pricing', 'ad'))
    # the suggested mid (decision 177) is off unless a test asks for it: the other tests run on the role prices they were
    # written for (test_mid_bid.py turns it on)
    s['mid_bid'] = dict(s.get('mid_bid') or {}, enabled=bool(placement.get('mid', False)))
    # For Growth as before decision 167 (30 quiet days, no new-SKC trigger)
    s['growth'] = dict(s.get('growth') or {}, enabled_default=False, quiet_days=30, new_skc_min_days=None)
    return s


def product(**over):
    p = dict(asin=ASIN, product='Test cards', sku='TEST-SKU', campaign_prefix=f'Cards - {ASIN} - ', profit_per_unit=5.0,
             registry=dict(bid_owner='AI', stage='ai', owner_since='2026-09-01'), auto=dict(AUTO))
    p.update(over)
    return p


def no_mid(out):
    """config.json as the tests written before decision 177 read it: the suggested mid off."""
    return dict(out, mid_bid=dict(out.get('mid_bid') or {}, enabled=False)) if isinstance(out, dict) else out


@contextlib.contextmanager
def without_mid():
    """plan.main() reads the live config.json, where the suggested mid (decision 177) is on, so a fixture without Amazon's
    mids would stop for them (exit 2). The main() tests written before it read it off here; test_mid_bid.py tests the rule."""
    real = planner.read_json

    def read(path, *a, **k):
        out = real(path, *a, **k)
        return no_mid(out) if os.path.basename(str(path)) == 'config.json' else out
    with unittest.mock.patch.object(planner, 'read_json', read):
        yield


def query(text, volume, total_clicks, total_purchases, asin_clicks, asin_purchases, observed_days=84):
    return dict(ASIN=ASIN, Query=text, QueryVolume=volume, TotalClicks=total_clicks, TotalPurchase=total_purchases,
                AsinClicks=asin_clicks, AsinPurchase=asin_purchases, AsinImpressions=100, TotalImpressions=10000,
                QueryObservedDayCount=observed_days)


def search_term(text, campaign, clicks, orders, spend, ad_group=None):
    cid, ag = IDS[campaign]
    ag = ad_group or ag
    return dict(ASIN=ASIN, SearchTerm=text, CampaignName=campaign, CampaignId=cid, AdGroupId=ag, AdGroupName='Group',
                AdType='SP', Clicks=clicks, Orders=orders, Spend=spend, Sales=orders * 10, Impressions=clicks * 20)


def keyword(kid, text, match, campaign, bid, clicks, orders, spend):
    cid, ag = IDS[campaign]
    return dict(KeywordId=kid, Keyword=text, MatchType=match, CampaignName=campaign, CampaignId=cid, AdGroupId=ag,
                AdGroupName='Group', AdType='SP', Bid=bid, Clicks=clicks, Orders=orders, Spend=spend, Sales=orders * 10)


def target(tid, text, bid, clicks, orders, spend):
    cid, ag = IDS[PT]
    return dict(TargetId=tid, TargetText=text, TargetType='product', CampaignName=PT, CampaignId=cid, AdGroupId=ag,
                AdType='SP', Bid=bid, Clicks=clicks, Orders=orders, Spend=spend)


QUERIES = [query('blank cards', 2000, 800, 80, 30, 6),      # beats the market, no exact campaign yet: promoted
           query('thank you cards', 1500, 600, 60, 40, 8),  # beats the market, owns an exact campaign already
           query('gold cards', 500, 300, 30, 30, 0)]        # trails the market
SEARCH_TERMS = [search_term('blank cards', STW, 20, 4, 12), search_term('blank cards', AUTO_CAMPAIGN, 10, 1, 6),
                search_term('thank you cards', SKC, 40, 8, 30), search_term('thank you cards', AUTO_CAMPAIGN, 5, 0, 3),
                search_term('gold cards', STW, 10, 0, 5), search_term('random search', AUTO_CAMPAIGN, 3, 0, 2)]
KEYWORDS = [keyword('1', 'thank you cards', 'exact', SKC, 0.80, 40, 8, 30),   # invest re-price up to breakeven
            keyword('2', 'blank cards', 'exact', STW, 0.50, 20, 3, 12),       # duplicate of the promoted search
            keyword('3', 'gold cards', 'exact', STW, 0.50, 10, 0, 5),         # trails the market: a cut
            keyword('4', 'cards', 'broad', BROAD, 0.30, 10, 1, 6),            # raise to breakeven, past +25%: capped
            keyword('5', 'greeting cards', 'phrase', BROAD, 1.50, 20, 0, 9),  # discovery cut
            keyword('6', 'birthday cards', 'exact', STW, 0.40, 10, 0, 3),     # raise above breakeven, no proof: monitor
            keyword('7', 'thank you cards', 'broad', LOW, 0.20, 5, 0, 1),     # audience campaign: kept as it is
            keyword('8', 'gift cards', 'exact', STW, 0.50, 0, 0, 0)]          # already at its price: no change
TARGETS = [target('301', 'asin="B0SAMP0036"', 0.60, 25, 0, 15),  # 25 clicks, no order: paused
           target('302', 'asin="B0SAMP0037"', 0.30, 10, 2, 6)]   # raise to its breakeven, past +25%: capped
SUGGESTED = {'blank cards': [0.55, 0.70, 0.90], 'thank you cards': [0.55, 0.80, 1.00]}
# a one-word search promoted like blank cards: a head term stays a person's call (decision 107), so a run with it has rows
# for a person and a Bids item (until 2026-10-23 a non-standard budget did this)
HEAD_TERM = dict(queries=QUERIES + [query('notecards', 2000, 800, 80, 30, 6)],
                 search_terms=SEARCH_TERMS + [search_term('notecards', STW, 20, 4, 12)],
                 suggested=dict(SUGGESTED, notecards=[0.55, 0.70, 0.90]))


def campaign(name, budget=10, tos=0):
    cid = IDS[name][0]
    return dict(campaignId=cid, name=name, state='ENABLED', budget=dict(budget=budget),
                optimizations=dict(bidSettings=dict(bidStrategy='SALES_DOWN_ONLY', bidAdjustments=dict(
                    placementBidAdjustments=[dict(placement='PLACEMENT_TOP', percentage=tos)]))))


def write(path, data):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh)


# E6: an enabled product needs both of these files, or its data counts as stale. The fixture supplies fresh ones (the
# price last changed 30 days ago, 60 days of stock), so a test about something else plans as it always did; a test of
# the missing files passes lane_files=False.
LANE_FILES = {'price_change.json': {'days_since': 30}, 'inventory_cover.json': {'cover_days': 60}}
FRESH_LANE_INPUTS = dict(soldscope={}, inventory_cover={'cover_days': 60}, price_change={'days_since': 30}, reviews=None)


# Decision 135 (2026-10-25): plan.main() prices every live keyword and target, so it stops without the live reads. The
# fixture supplies them empty (nothing beyond the Scale Insights rows), so a test about something else plans as it always
# did; a test of the live inventory passes its own through extra, and inventory=False leaves them out.
INVENTORY_FILES = {'live_keywords_p1.json': [], 'live_targets_p1.json': [], 'sd_targets_p1.json': {'data': []},
                   'ad_campaigns_p1.json': {'data': []},   # decision 156: the campaigns by product ad
                   'live_ad_groups_p1.json': [], 'sb_campaigns_p1.json': [],   # the reads coverage needs (decision 156)
                   'settlement.json': {'data': []}}   # decision 169: nothing settled, so the stored referral rate stands


def make_run(run, data_through='2026-10-12', queries=None, search_terms=None, keywords=None, targets=True,
             suggested=None, extra=None, more_campaigns=(), lane_files=True, inventory=True):
    os.makedirs(run, exist_ok=True)
    for name, data in INVENTORY_FILES.items():
        path = os.path.join(run, name)
        if inventory and not os.path.exists(path):
            write(path, data)
        elif not inventory and os.path.exists(path):
            os.remove(path)
    for name in LANE_FILES:
        if os.path.exists(os.path.join(run, name)):
            os.remove(os.path.join(run, name))  # a run folder planned again keeps only what this call asks for
    if lane_files:
        extra = dict(LANE_FILES, **(extra or {}))
    page = dict(Queries=queries if queries is not None else QUERIES)
    if data_through:
        page['Meta'] = dict(data_through=data_through)
    write(os.path.join(run, 'sqp_p1.json'), page)
    write(os.path.join(run, 'st_p1.json'), dict(data=search_terms if search_terms is not None else SEARCH_TERMS))
    write(os.path.join(run, 'kw_p1.json'), dict(data=keywords if keywords is not None else KEYWORDS))
    if targets:
        write(os.path.join(run, 'pt_p1.json'), dict(data=TARGETS))
    write(os.path.join(run, 'suggested_bids.json'), suggested if suggested is not None else SUGGESTED)
    write(os.path.join(run, 'campaigns.json'),
          dict(items=[campaign(STW), campaign(AUTO_CAMPAIGN), campaign(BROAD), campaign(LOW), campaign(SKC, tos=50),
                      campaign(PT)] + list(more_campaigns)))
    for name, data in (extra or {}).items():
        if data is None:   # a read the test leaves out
            if os.path.exists(os.path.join(run, name)):
                os.remove(os.path.join(run, name))
        else:
            write(os.path.join(run, name), data)
    return run


def read_payloads(run, folder):
    """The payload files of payloads/<folder>, without its rows.json (read_rows)."""
    path = os.path.join(run, 'payloads', folder)
    out = {}
    for name in sorted(os.listdir(path)):
        if name == 'rows.json':
            continue
        with open(os.path.join(path, name), encoding='utf-8') as fh:
            out[name] = json.load(fh)
    return out


def read_rows(run, folder):
    with open(os.path.join(run, 'payloads', folder, 'rows.json'), encoding='utf-8') as fh:
        return json.load(fh)


def by_type(out, ctype):
    return [x for x in out['changes'] if x['type'] == ctype]


def one(out, ctype, **match):
    rows = [x for x in by_type(out, ctype) if all(x.get(k) == v for k, v in match.items())]
    assert len(rows) == 1, (ctype, match, rows)
    return rows[0]


def is_raise(x):
    return x['type'] in lanes.BID_TYPES and x.get('current') is not None and (x.get('new_proposed') or x['new']) > x['current']


class PlannerLanesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.run_dir = os.path.join(self.tmp, 'run')

    def plan(self, cfg=None, shared=None, now=NOW, write_out=True, **run):
        make_run(self.run_dir, **run)
        out = planner.build(ASIN, cfg or product(), shared or shared_config(), self.run_dir, 'weekly', TODAY, now_utc=now)
        if write_out:
            planner.write_outputs(self.run_dir, out, shared or shared_config(), ASIN)
        return out

    # --- the brief's five tests ---------------------------------------------------------------------------------
    def test_shadow_writes_review_only(self):
        out = self.plan(cfg=product(auto=dict(AUTO, enabled=False)))
        self.assertIs(out['summary'][0]['shadow'], True)
        self.assertEqual(os.listdir(os.path.join(self.run_dir, 'payloads', 'auto')), [])
        for x in out['changes']:
            self.assertIn(x['lane'], ('auto', 'human', 'monitor'), x)
            self.assertTrue(x['lane_reason'])
        review = read_payloads(self.run_dir, 'review')
        # review/ holds every row the planner would send out (B10): a monitor row is held, in held/, so a whole-run yes on
        # the preview can't apply what the planner holds
        bids = {row['keywordId']: row['bid'] for row in review['4_bids_01.json']}
        self.assertEqual(one(out, 'Bid change', keyword_id='6')['lane'], 'monitor')
        self.assertNotIn('6', bids)
        self.assertEqual(read_payloads(self.run_dir, 'held'), {'4_bids_01.json': [dict(type='sp_keywords', keywordId='6', bid=0.5)]})
        self.assertEqual(read_rows(self.run_dir, 'held'), {'4_bids_01.json': ['Bid change:6']})
        # an auto row past the +25% cap is written at the cap, the auto lane's call (A5), so the preview's yes and a
        # dashboard agree apply the same bid; the row keeps the bid as proposed
        capped = one(out, 'Bid change', keyword_id='4')
        self.assertEqual(capped['lane'], 'auto')
        self.assertEqual(bids['4'], capped['new_capped'])
        self.assertEqual(capped['new_proposed'], capped['new'])
        self.assertLess(capped['new_capped'], capped['new'])
        target = one(out, 'Target bid change', target_id='302')
        self.assertEqual(review['9_target_bids_01.json'], [dict(type='sp_targets', targetId='302', bid=target['new_capped'])])
        self.assertEqual(sorted(review), ['1_new_campaigns.json', '1b_new_skc_specs.json', '3_pauses.json',
                                          '4_bids_01.json', '6_negatives_01.json', '9_target_bids_01.json',
                                          '9_target_pauses.json'])

    def test_enabled_splits(self):
        out = self.plan()
        self.assertIs(out['summary'][0]['shadow'], False)
        auto, review = read_payloads(self.run_dir, 'auto'), read_payloads(self.run_dir, 'review')
        auto_bids = {row['keywordId'] for row in auto['4_bids_01.json']}
        self.assertEqual(auto_bids, {x['keyword_id'] for x in by_type(out, 'Bid change') if x['lane'] == 'auto'})
        self.assertEqual(auto_bids, {'1', '3', '4', '5'})
        self.assertEqual(one(out, 'Bid change', keyword_id='6')['lane'], 'monitor')
        self.assertNotIn('"keywordId": "6"', json.dumps([auto, review]))  # monitor rows are held back
        # every funnel negative applies on its own since autonomous runs (2026-10-22), the promotion's and the others'
        self.assertNotIn('6_negatives_01.json', review)
        self.assertEqual(sorted(row['keywordText'] for row in auto['6_negatives_01.json']),
                         ['blank cards', 'blank cards', 'thank you cards'])
        self.assertNotIn('4_bids_01.json', review)
        counts = out['summary'][0]['lanes']
        self.assertEqual(sum(counts.values()), len(out['changes']))
        self.assertEqual(counts, {lane: sum(x['lane'] == lane for x in out['changes']) for lane in ('auto', 'human', 'monitor')})

    def test_old_inputs_still_plan(self):
        """Review Focus 1: a product file without auto, decisions or registry, and a run without pt* or SoldScope. Since
        2026-10-22 config.json turns Auto on for every product, so a product file without its own block is enabled."""
        make_run(self.run_dir, targets=False)
        data = os.path.join(self.tmp, 'data')
        os.makedirs(os.path.join(data, 'asins'))
        old = {k: v for k, v in product().items() if k not in ('auto', 'registry')}
        write(os.path.join(data, 'asins', f'{ASIN}.json'), old)
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--data', data, '--today', TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), without_mid():
            planner.main()
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            saved = json.load(fh)
        self.assertIs(saved['summary'][0]['shadow'], False)
        self.assertTrue(saved['changes'])
        self.assertTrue(all(x['lane'] in ('auto', 'human', 'monitor') for x in saved['changes']))
        self.assertTrue(os.listdir(os.path.join(self.run_dir, 'payloads', 'auto')))  # enabled: auto/ holds the Auto rows
        self.assertIn('apply_after', saved['summary'][0])

    def test_main_prices_the_bands_after_the_placement_refresh(self):
        # the placement snapshot shows the invest campaign at +100% top of search; main() re-prices the re-rank with it,
        # so the bands and the promotion's band words must use the refreshed spend, not build()'s
        make_run(self.run_dir)
        cid = IDS[SKC][0]
        live = campaign(SKC, budget=8, tos=100)
        write(os.path.join(self.run_dir, 'campaigns.json'),
              dict(items=[campaign(STW), campaign(AUTO_CAMPAIGN), campaign(BROAD), campaign(LOW), campaign(SKC, budget=8, tos=50),
                          campaign(PT)]))
        row = dict(asin=ASIN, campaignId=cid, placement='Top of Search on-Amazon')
        for suffix in ('30', '90', '_recent'):
            row.update({k + suffix: v for k, v in dict(clicks=60, orders=12, spend=24, sales=120).items()})
        write(os.path.join(self.run_dir, 'placement_inputs.json'),
              dict(asin=ASIN, complete=True, as_of='2026-10-18', retrieved_at='2026-10-18T18:00:00+08:00',
                   windows={'30d': ['2026-09-04', '2026-10-03'], '90d': ['2026-07-06', '2026-10-03'],
                            'recent': ['2026-09-18', '2026-10-17']},
                   campaigns=[live], live_asins={cid: [ASIN]}, rows=[row]))
        skill = os.path.join(self.tmp, 'skill')
        os.makedirs(os.path.join(skill, 'data', 'asins'))
        write(os.path.join(skill, 'config.json'), shared_config())
        write(os.path.join(skill, 'data', 'asins', f'{ASIN}.json'), product())
        built = planner.build(ASIN, product(), shared_config(), self.run_dir, 'weekly', TODAY, now_utc=NOW)
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--skill', skill, '--today', TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), without_mid():
            planner.main()
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            saved = json.load(fh)
        refreshed = next(r for r in saved['rerank'] if r['keyword'] == 'thank you cards')
        before = next(r for r in built['rerank'] if r['keyword'] == 'thank you cards')
        self.assertEqual(refreshed['tos'], 100)
        self.assertNotEqual(refreshed['spend'], before['spend'])
        self.assertEqual(saved['bands']['thank you cards'], refreshed['spend'])
        promo = next(x for x in saved['changes'] if x['type'] == 'New exact campaign')
        left = saved['band_product_month'] - refreshed['spend']
        self.assertIn(f'of ${left:.2f} left', promo['lane_reason'])

    def test_lock_forces_human(self):
        decisions = [dict(id='Bid change:5', what='decline', by='Lee', until='2026-11-16'),
                     dict(id='Bid change:3', what='approve', by='Lee', until='2026-10-18'),  # expired
                     dict(id='4', what='decline', by='Kim', until='2026-11-16')]  # a bare keyword id
        out = self.plan(cfg=product(decisions=decisions))
        greeting = one(out, 'Bid change', keyword_id='5')
        self.assertEqual(greeting['lane'], 'human')
        self.assertEqual(greeting['lane_reason'], 'decided by Lee on 2026-10-19 (declined this row); it holds until '
                                                  '2026-11-16, so a person decides')
        bare = one(out, 'Bid change', keyword_id='4')
        self.assertEqual(bare['lane'], 'human')
        self.assertEqual(bare['new'], 0.62)  # a person sees the bid as proposed, not the automatic cap
        self.assertNotIn('new_capped', bare)
        self.assertNotIn('new_proposed', bare)
        self.assertEqual(one(out, 'Bid change', keyword_id='3')['lane'], 'auto')  # an expired lock no longer holds

    def test_rank_experiments_lock_their_search_unless_dismissed(self):
        rows = [dict(keyword='cards', status='launched', approved_to_apply=True, review_on='2026-11-16'),
                dict(keyword='Greeting  Cards!', status='proposed_not_applied'),  # normalised like the planner's searches
                dict(keyword='gold cards', status='dismissed', approved_to_apply=True, review_on='2026-11-16'),
                dict(keyword='birthday cards', status='Declined by Kim'),
                dict(keyword='thank you cards', status='approved', review_on='2026-10-18')]  # its review date has passed
        out = self.plan(cfg=product(proposed_rank_experiments=dict(as_of='2026-10-18', rows=rows)), write_out=False)
        approved = one(out, 'Bid change', keyword_id='4')
        self.assertEqual(approved['lane'], 'human')
        self.assertEqual(approved['lane_reason'], 'a person approved a rank experiment on this search until 2026-11-16')
        proposed = one(out, 'Bid change', keyword_id='5')
        self.assertEqual(proposed['lane'], 'human')
        self.assertEqual(proposed['lane_reason'], 'a rank experiment is proposed on this search; a person decides it first')
        self.assertEqual(one(out, 'Bid change', keyword_id='3')['lane'], 'auto')  # dismissed: no lock
        self.assertEqual(one(out, 'Bid change', keyword_id='6')['lane'], 'monitor')  # declined: no lock
        # approved, but past its review date: the lock no longer holds it, but since the merge of 2dcb21c the planner
        # proposes nothing for it. An invest search named in proposed_rank_experiments is an existing rank investment, so
        # the visibility review keeps it at its live bid for its own review (plan.py deferred_rank_terms): no Bid change.
        self.assertEqual([x for x in by_type(out, 'Bid change') if x.get('keyword_id') == '1'], [])
        kept = next(p for p in out['keyword_plan'] if p['keyword_id'] == '1')
        self.assertTrue(kept['action'].startswith('Keep pending visibility review'))
        self.assertIn('thank you cards', out['visibility_review']['retained_rank_searches'])

    def test_a_decisions_list_that_cannot_be_read_sends_everything_to_a_person(self):
        out = self.plan(cfg=product(decisions={'id': 'Bid change:5', 'until': '2026-11-16'}), write_out=False)
        self.assertTrue(out['changes'])
        for x in out['changes']:
            self.assertEqual((x['lane'], x['lane_reason']), ('human', "the product's decisions list can't be read"))

    def test_band_from_soldscope_when_no_sqp(self):
        # Since the merge of 2dcb21c a search SQP sees with none of the market's clicks has no same-query benchmark: its
        # index is unknown and it stays a Test (Codex's visibility rule), so the planner never promotes it or prices a
        # band for it. Before the merge it was promoted on its search-term record and its band priced from SoldScope.
        queries = QUERIES + [query('new search', 300, 0, 0, 0, 0)]  # SQP sees the search but none of its clicks
        terms = SEARCH_TERMS + [search_term('new search', STW, 12, 3, 8)]
        suggested = dict(SUGGESTED, **{'new search': [0.40, 0.60, 0.80]})
        out = self.plan(queries=queries, search_terms=terms, suggested=suggested, write_out=False,
                        extra={'soldscope_volume.json': {'new search': 3000}})
        term = next(t for t in out['terms'] if t['term'] == 'new search')
        self.assertEqual((term['role'], term['index'], term['index_status']), ('Test', None, 'unknown_market_benchmark'))
        self.assertEqual([x for x in by_type(out, 'New exact campaign') if x['keyword'] == 'new search'], [])
        self.assertNotIn('new search', out['bands'])

        # band_rows still prices a re-rank row SQP has no clicks for from SoldScope (spec section 4), should one reach it:
        # SoldScope's monthly searches x the product's market click rate from SQP
        shared = shared_config()
        out = dict(terms=[dict(term='blank cards', sqp_volume=2000, sqp_total_clicks=800, observed_days=84, cvr_est=0.2,
                               market_cvr=0.1),
                          dict(term='new search', sqp_volume=300, sqp_total_clicks=0, observed_days=84, cvr_est=0.2,
                               market_cvr=None)],
                   rerank=[dict(keyword='new search', cpc=0.6, budget=5, spend=0, orders=0, net=0)])
        row, clicks = plan_lanes.band_rows(out, {'soldscope': {}}, shared, 5.0)['new search']
        self.assertEqual((row['spend'], clicks), (0, 0))  # no clicks to price: no band, which fails safe
        row, clicks = plan_lanes.band_rows(out, {'soldscope': {'new search': 3000}}, shared, 5.0)['new search']
        rate = 800 / (2000 + 300)
        spend = min(0.1 * 3000 * rate * 0.6, 5 * 30)
        self.assertAlmostEqual(clicks, 3000 * rate, places=6)
        self.assertEqual(row['spend'], round(spend))
        self.assertEqual(row['net'], round(spend / 0.6 * min(0.2, 1.5 * 0.09) * 5.0 - spend))
        self.assertEqual(out['rerank'][0]['spend'], 0)  # the re-rank table itself stays SQP-only

    def test_deferred_invest_searches_count_as_planned_invest_spend(self):
        # Merge of 2dcb21c: an existing rank investment (in the invest log) is kept at its live bid for its own review and
        # left out of the re-rank forecast, but it still spends: rerank_held carries its modelled spend, and the lanes
        # count it as invest spend already planned (Kim's level), as they did before the merge
        out = self.plan(cfg=product(invest_log={'thank you cards': dict(since='2026-10-05', role='Invest')}), write_out=False)
        self.assertNotIn('thank you cards', [r['keyword'] for r in out['rerank']])
        held = one(dict(changes=[dict(r, type='held') for r in out['rerank_held']]), 'held', keyword='thank you cards')
        self.assertEqual((held['bid'], held['tos'], held['budget']), (0.80, 50, 10))  # its live bid, top of search and budget
        self.assertGreater(held['spend'], 0)
        self.assertEqual(out['summary'][0]['planned_invest_month_start'], held['spend'])
        self.assertIn('thank you cards', out['bands'])
        # the same plan without the invest log: thank you cards is re-priced and in the re-rank, as before the merge
        out = self.plan(write_out=False)
        self.assertIn('thank you cards', [r['keyword'] for r in out['rerank']])
        self.assertEqual(out['rerank_held'], [])

    def test_the_investment_guide_is_information_only(self):
        # Kim, 2026-10-22, decision 99: $2,000 a month a product is a guide, not a gate. The summary carries the product's
        # planned invest a month once this run's Auto promotions go out, and a flag when it is above the guide
        self.assertEqual(plan_lanes.invest_guide(2100.456, 2000), (2100.46, True))
        self.assertEqual(plan_lanes.invest_guide(2000, 2000), (2000, False))
        self.assertEqual(plan_lanes.invest_guide(5000, None), (5000, False))   # no readable guide: no flag
        self.assertFalse(hasattr(plan_lanes, 'kim_level'))
        self.assertFalse(hasattr(plan_lanes, 'program_level'))

    # --- R8's extra tests ---------------------------------------------------------------------------------------
    def test_promotion_bundle_is_auto_together(self):
        out = self.plan()
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['lane'], promo['tos'], promo['budget']), ('auto', 0, 10))
        self.assertIn('fits the product', promo['lane_reason'])
        pause = one(out, 'Pause keyword', keyword_id='2')
        self.assertEqual(pause['orders90'], 3)  # alone, a pause with orders would need a person
        negatives = [x for x in by_type(out, 'Negative exact') if x['keyword'] == 'blank cards']
        self.assertEqual(len(negatives), 2)
        for member in [pause] + negatives:
            self.assertEqual(member['lane'], 'auto')
            self.assertTrue(member['lane_reason'].startswith('part of the promotion of blank cards: '), member['lane_reason'])
            self.assertEqual(member['opportunity'], promo['opportunity'])
        outside = one(out, 'Negative exact', keyword='thank you cards')
        self.assertEqual(outside['lane'], 'auto')  # a funnel negative for a search not promoted this run (since 2026-10-22)
        auto = read_payloads(self.run_dir, 'auto')
        self.assertEqual([c['name'] for c in auto['1_new_campaigns.json']], [promo['campaign']])
        self.assertEqual([p['keywordId'] for p in auto['3_pauses.json']], ['2'])
        self.assertEqual(promo['modelled_spend_month'], next(r['spend'] for r in out['rerank'] if r['keyword'] == 'blank cards'))

    def test_a_duplicate_pause_with_orders_outside_a_promotion_applies_on_its_own(self):
        # 'thank you cards' already owns its exact campaign, so this copy is paused, and it is no promotion's bundle. Until
        # 2026-10-22 a pause with orders waited for a person; since autonomous runs it applies on its own (decision 98)
        copy_kw = keyword('9', 'thank you cards', 'exact', STW, 0.60, 12, 2, 7)
        out = self.plan(keywords=KEYWORDS + [copy_kw], write_out=False)
        pause = one(out, 'Pause keyword', keyword_id='9')
        self.assertEqual(pause['orders90'], 2)
        self.assertEqual((pause['lane'], pause['lane_reason']), ('auto', 'pause: a cut is never held back'))

    # A $4.50 loss line leaves 'blank cards' (modelled at -$4 a month) inside its own band but shrinks the band of
    # 'thank you cards' (-$5), whose spend is already planned: the product's pooled band is then short (ruling A1 made
    # the old $1 limit trip the search's own band first). Information only since decision 100 (2026-10-22).
    SHORT_BAND = dict(AUTO, max_loss_month=4.5)

    def test_unmodelled_promotion_keeps_auto_lane_and_unknown_forecast(self):
        make_run(self.run_dir)
        shared, cfg = shared_config(), product()
        out = planner.build(ASIN, cfg, shared, self.run_dir, 'weekly', TODAY, with_lanes=False)
        # The search has enough conversion proof, but no forecast to size its spend.
        out['rerank'] = [row for row in out['rerank'] if row['keyword'] != 'blank cards']
        plan_lanes.assign(out, cfg, shared, 'weekly', planner.load_lane_inputs(self.run_dir), TODAY, NOW)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual(promo['lane'], 'auto')
        self.assertIsNone(promo['modelled_spend_month'])
        self.assertIn("its monthly spend isn't modelled", promo['lane_reason'])
        self.assertFalse(promo['over_invest_band'])
        planner.write_outputs(self.run_dir, out, shared, ASIN)
        self.assertEqual(len(read_payloads(self.run_dir, 'auto')['1_new_campaigns.json']), 1)

    def test_a_promotion_past_the_products_band_goes_out_with_its_bundle_and_says_so(self):
        # until 2026-10-22 a short band sent the promotion and its bundle to a person; decision 100 ("don't cap the
        # promotion"): it goes out, the row is flagged over_invest_band and the summary lists it for the Slack recap
        out = self.plan(cfg=product(auto=self.SHORT_BAND))
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual(promo['own_band_month'], promo['modelled_spend_month'])  # it fits its own search's band
        self.assertEqual(promo['lane'], 'auto')
        self.assertIn("it goes past the product's monthly invest band ($25.00, with $22.90 left) (information only: no "
                      'cap, decision 100)', promo['lane_reason'])
        self.assertIs(promo['over_invest_band'], True)
        self.assertIs(promo['over_loss_line'], False)
        members = [one(out, 'Pause keyword', keyword_id='2')] + [x for x in by_type(out, 'Negative exact')
                                                                 if x['keyword'] == 'blank cards']
        for member in members:
            self.assertEqual(member['lane'], 'auto')
            self.assertIn('part of the promotion of blank cards', member['lane_reason'])
        auto = read_payloads(self.run_dir, 'auto')
        self.assertIn('1_new_campaigns.json', auto)
        self.assertIn('3_pauses.json', auto)
        self.assertEqual(sorted(r['keywordText'] for r in auto['6_negatives_01.json']),
                         ['blank cards', 'blank cards', 'thank you cards'])
        s = out['summary'][0]
        self.assertEqual((s['over_invest_band'], s['invest_band_month']), (['blank cards'], out['band_product_month']))
        self.assertEqual((s['over_loss_line'], s['loss_line_month']), ([], 4.5))
        # with the standard $60 line the band has room: nothing is flagged
        plain = self.plan(write_out=False)
        self.assertIs(one(plain, 'New exact campaign', keyword='blank cards')['over_invest_band'], False)
        self.assertEqual((plain['summary'][0]['over_invest_band'], plain['summary'][0]['over_loss_line']), ([], []))

    def test_a_loss_capped_promotion_goes_out_and_is_flagged(self):
        """A1 (C1): 'kids cards' is the bigger prize, so it is judged first, but it is modelled to lose far more than $60 a
        month, so its own band is shrunk. Until 2026-10-22 it went to a person; since decision 100 it goes out, its reason
        names the $60 loss line, the row is flagged over_loss_line and the summary lists it. 'party cards', inside the
        line, is not flagged."""
        queries = QUERIES + [query('kids cards', 60000, 8000, 400, 60, 4), query('party cards', 25000, 9500, 950, 60, 10)]
        suggested = dict(SUGGESTED, **{'kids cards': [1.00, 1.20, 1.50], 'party cards': [0.60, 0.80, 1.00]})
        out = self.plan(queries=queries, suggested=suggested, write_out=False)
        rerank = {r['keyword']: r for r in out['rerank']}
        kids, party = (one(out, 'New exact campaign', keyword=k) for k in ('kids cards', 'party cards'))
        self.assertGreater(kids['opportunity'], party['opportunity'])  # judged first
        self.assertLess(rerank['kids cards']['net'], -AUTO['max_loss_month'])
        self.assertEqual((kids['own_band_month'], kids['modelled_net_month']),
                         (out['bands']['kids cards'], rerank['kids cards']['net']))
        self.assertLess(kids['own_band_month'], kids['modelled_spend_month'])
        self.assertEqual(kids['lane'], 'auto')
        self.assertIn(f"modelled to lose ${-rerank['kids cards']['net']:.2f} a month, over the $60 loss line for one search",
                      kids['lane_reason'])
        self.assertEqual((kids['over_loss_line'], party['over_loss_line']), (True, False))
        self.assertEqual(party['lane'], 'auto')
        self.assertEqual(party['own_band_month'], party['modelled_spend_month'])  # it loses less than $60 a month
        s = out['summary'][0]
        self.assertEqual(s['over_loss_line'], [dict(search='kids cards',
                                                     modelled_net_month=round(rerank['kids cards']['net'], 2))])
        self.assertEqual(s['loss_line_month'], 60)

    def test_the_raise_past_the_products_own_cap_waits_for_the_next_run(self):
        shared = shared_config()
        self.assertEqual(shared['auto']['max_raises'], 20)  # config allows 20; the product file allows 3
        extra = [keyword('10', 'card style', 'broad', BROAD, 0.30, 10, 1, 6)]
        out = self.plan(cfg=product(auto=dict(AUTO, max_raises=3)), shared=shared, keywords=KEYWORDS + extra, write_out=False)
        self.assertEqual(sum(is_raise(x) and x['lane'] == 'auto' for x in out['changes']), 3)
        held = [x for x in out['changes'] if is_raise(x) and 'used up its 3 automatic raises' in x['lane_reason']]
        self.assertEqual(len(held), 1)
        # decision 107 (2026-10-23): held for the next run, not a person's call
        self.assertEqual(held[0]['lane'], 'monitor')
        self.assertIn('so it goes out on the next run', held[0]['lane_reason'])
        self.assertFalse([x for x in out['changes'] if x['lane'] == 'human'])
        # A5 (M6): held back only for the run's cap, it keeps the capped bid, and held/ writes that, not the full raise
        self.assertLess(held[0]['new_capped'], held[0]['new'])
        self.assertEqual(held[0]['new_proposed'], held[0]['new'])
        planner.write_outputs(self.run_dir, out, shared, ASIN)
        review = read_payloads(self.run_dir, 'held')
        written = [r['bid'] for f, rows in review.items() for r in rows
                   if str(r.get('keywordId') or r.get('targetId')) == str(held[0].get('keyword_id') or held[0].get('target_id'))]
        self.assertEqual(written, [held[0]['new_capped']])

    def test_an_auto_raise_past_the_cap_writes_the_capped_bid(self):
        out = self.plan()
        row = one(out, 'Bid change', keyword_id='4')
        self.assertEqual(row['lane'], 'auto')
        self.assertEqual(row['new'], 0.37)  # 0.30 + 25%, rounded down to the cent
        self.assertGreater(row['new_proposed'], row['new'])
        self.assertEqual(row['change'], round(0.37 / 0.30 - 1, 3))
        bids = {b['keywordId']: b['bid'] for b in read_payloads(self.run_dir, 'auto')['4_bids_01.json']}
        self.assertEqual(bids['4'], 0.37)
        tgt = one(out, 'Target bid change', target_id='302')
        self.assertEqual((tgt['lane'], tgt['new']), ('auto', 0.37))
        self.assertEqual(read_payloads(self.run_dir, 'auto')['9_target_bids_01.json'],
                         [dict(type='sp_targets', targetId='302', bid=0.37)])

    def test_a_sunday_run_is_immediately_eligible(self):
        out = self.plan(now=datetime(2026, 10, 18, 16, 35, tzinfo=UTC), write_out=False)
        self.assertEqual(out['summary'][0]['apply_after'], '2026-10-18')
        self.assertEqual(self.plan(write_out=False)['summary'][0]['apply_after'], '2026-10-19')

    def test_old_sqp_is_planned_on_and_its_age_reported(self):
        # decision 172 (Kim, 2026-10-30, "just take the latest SQP data that is available and use it"): SQP of any age is
        # planned on, Auto or shadow; the summary says how old it was. Until then over 10 days stopped the run (decision 168)
        out = self.plan(data_through='2026-10-08', write_out=False)
        self.assertIsNone(out['summary'][0]['stale_reason'])
        self.assertEqual(out['summary'][0]['sqp_age_days'], 11)
        self.assertEqual(self.lanes_of(out), self.lanes_of(self.plan(data_through='2026-10-18', write_out=False)))
        shadow = self.plan(cfg=product(auto=dict(AUTO, enabled=False)), data_through='2026-09-01', write_out=False)
        self.assertIsNone(shadow['summary'][0]['stale_reason'])
        self.assertEqual(shadow['summary'][0]['sqp_age_days'], 48)

    def lanes_of(self, out):
        return {x['row_id']: (x['lane'], x['lane_reason']) for x in out['changes']}

    def test_owner_since_five_days_ago_is_onboarding(self):
        # since autonomous runs (2026-10-22, decision 98) the onboarding reason is reported and the rows are judged as usual
        cfg = product(registry=dict(bid_owner='AI', stage='ai', owner_since='2026-10-14'))
        out = self.plan(cfg=cfg, write_out=False)
        self.assertEqual(out['summary'][0]['onboarding_reason'],
                         "the AI took over this product's bids on 2026-10-14, less than 14 days ago")
        self.assertEqual(self.lanes_of(out), self.lanes_of(self.plan(write_out=False)))
        self.assertFalse(any('onboarding' in x['lane_reason'] for x in out['changes']))

    # --- the rest of the rulings -----------------------------------------------------------------------------
    def test_no_owner_since_is_onboarding_and_says_so(self):
        out = self.plan(cfg=product(registry=dict(bid_owner='AI', stage='ai')), write_out=False)
        no_date = 'the registry has no date for when the AI took over its bids'
        self.assertEqual(out['summary'][0]['onboarding_reason'], no_date)
        self.assertEqual(self.lanes_of(out), self.lanes_of(self.plan(write_out=False)))  # judged as usual since 2026-10-22

    def test_onboarding_stage_and_onboard_mode_are_onboarding(self):
        out = self.plan(cfg=product(registry=dict(bid_owner='AI', stage='onboarding', owner_since='2026-09-01')),
                        write_out=False)
        self.assertEqual(out['summary'][0]['onboarding_reason'], 'the registry still marks the product as onboarding')
        self.assertEqual(self.lanes_of(out), self.lanes_of(self.plan(write_out=False)))
        make_run(self.run_dir)
        out = planner.build(ASIN, product(), shared_config(), self.run_dir, 'onboard', TODAY, now_utc=NOW)
        self.assertIn('this is an onboarding run', out['summary'][0]['onboarding_reason'])
        # onboarding a product Kim added to the AI program applies on its own (decision 98): the standard Scale
        # Insights setup too
        rules = one(out, 'Scale Insights rules')
        self.assertEqual(rules['lane'], 'auto', rules['lane_reason'])

    def test_a_recent_price_change_holds_nothing(self):
        # decision 168: the run prices every row at the new settled profit straight away
        baseline = self.plan(write_out=False)
        out = self.plan(write_out=False, extra={'inventory_cover.json': {'cover_days': 14},
                                                'price_change.json': {'days_since': 5}})
        self.assertIsNone(out['summary'][0]['stale_reason'])
        self.assertEqual(self.lanes_of(out), self.lanes_of(self.plan(write_out=False, extra={'inventory_cover.json': {'cover_days': 14}})))
        self.assertTrue(any(x['lane'] == 'auto' for x in out['changes']))
        self.assertEqual(out['summary'][0]['stock_reorder']['cover_days'], 14)  # inventory stays visible for people
        self.assertIsNone(baseline['summary'][0]['stock_reorder'])
        with self.assertRaises(SystemExit) as stop:   # an unreadable cover file stops the run, saying what to save
            self.plan(write_out=False, extra={'inventory_cover.json': {'days': 30}})
        self.assertIn("doesn't say how many days of stock are left: save inventory_cover.json", str(stop.exception))

    def test_low_stock_parks_increases_and_lets_cuts_out(self):
        # Kim, 2026-10-31 (decision 174): under about 14 days of cover the run's increases wait For human unless a person
        # cleared the product; cuts, pauses and holds go out as usual (2026-10-24 to 10-31 every Auto row went out)
        baseline = self.plan(write_out=False)
        base_lanes = self.lanes_of(baseline)
        for cover in (14, 9, 1, 0):
            with self.subTest(cover=cover):
                out = self.plan(extra={'inventory_cover.json': {'cover_days': cover}})
                self.assertIsNone(out['summary'][0]['stale_reason'])
                rs = out['summary'][0]['stock_reorder']
                self.assertEqual((rs['cover_days'], rs['cleared']), (cover, None))
                self.assertTrue(rs['held'])
                for x in out['changes']:
                    if x['row_id'] in rs['held']:
                        self.assertEqual(x['lane'], 'human')
                        self.assertEqual(base_lanes[x['row_id']][0], 'auto')
                        self.assertTrue(plan_lanes.is_increase(x) or x.get('low_stock_hold') is not None)
                    else:
                        self.assertEqual(x['lane'], base_lanes[x['row_id']][0], x['row_id'])
                # a cut still goes out, unless it is a duplicate pause in a parked promotion's bundle (it waits with it)
                cuts = [x for x in baseline['changes'] if x['lane'] == 'auto' and lanes.is_cut(x) and x['row_id'] not in rs['held']]
                self.assertTrue(cuts)
                self.assertIn('Pause keyword:2', rs['held'])   # blank cards' duplicate, in its New exact campaign bundle
                self.assertTrue(all(next(y for y in out["changes"] if y["row_id"] == c["row_id"])["lane"] == "auto" for c in cuts))
        # 15 days is not low stock: nothing parked
        out = self.plan(write_out=False, extra={'inventory_cover.json': {'cover_days': 15}})
        self.assertEqual(self.lanes_of(out), base_lanes)
        self.assertIsNone(out['summary'][0]['stock_reorder'])

    def test_a_persons_stock_clearance_lets_the_increases_out(self):
        # B0SAMP0015, 2026-10-31: Kim cleared it because supply chain was on it
        base_lanes = self.lanes_of(self.plan(write_out=False))
        cleared = product(stock_clearance=dict(by='Kim', on=TODAY, why='supply chain is on it'))
        out = self.plan(cfg=cleared, write_out=False, extra={'inventory_cover.json': {'cover_days': 9}})
        self.assertEqual(self.lanes_of(out), base_lanes)
        rs = out['summary'][0]['stock_reorder']
        self.assertEqual((rs['held'], rs['cleared']['by'], rs['cleared']['why']), ([], 'Kim', 'supply chain is on it'))
        # a clearance lasts 7 days unless it names its own end
        old = product(stock_clearance=dict(by='Kim', on='2026-01-01'))
        self.assertTrue(self.plan(cfg=old, write_out=False, extra={'inventory_cover.json': {'cover_days': 9}})
                        ['summary'][0]['stock_reorder']['held'])

    # --- fix E: E6 (I6), a missing stock file is stale data while the Auto lane is on (decision 168: it stops the run) ---
    STOCK_MISSING = 'the inventory cover file is missing (needed while the Auto lane is on)'

    def test_an_enabled_product_without_its_stock_file_stops_and_needs_no_price_file(self):
        out = self.plan(lane_files=False, extra={'inventory_cover.json': {'cover_days': 60}}, write_out=False)
        self.assertIsNone(out['summary'][0]['stale_reason'])   # price_change.json is no longer needed (decision 168)
        for files in ({'price_change.json': {'days_since': 30}}, {}):
            with self.subTest(files=sorted(files)):
                with self.assertRaises(SystemExit) as stop:
                    self.plan(lane_files=False, extra=files)
                self.assertIn(f'Nothing planned: {self.STOCK_MISSING}: save inventory_cover.json', str(stop.exception))

    def test_a_shadow_product_without_its_price_or_stock_file_is_not_stale(self):
        out = self.plan(cfg=product(auto=dict(AUTO, enabled=False)), lane_files=False, write_out=False)
        self.assertIs(out['summary'][0]['shadow'], True)
        self.assertIsNone(out['summary'][0]['stale_reason'])
        self.assertEqual(one(out, 'Bid change', keyword_id='3')['lane'], 'auto')  # judged as usual: shadow shows the call
        # only an explicit true turns the lane on, so only that makes the files required
        out = self.plan(cfg=product(auto=dict(AUTO, enabled='yes')), lane_files=False, write_out=False)
        self.assertIsNone(out['summary'][0]['stale_reason'])

    def test_stale_reason_names_the_missing_files_only_when_enabled(self):
        self.assertIsNone(plan_lanes.stale_reason({}))
        self.assertIsNone(plan_lanes.stale_reason({}, enabled=False))
        self.assertTrue(plan_lanes.stale_reason({}, enabled=True).startswith(self.STOCK_MISSING))
        self.assertIsNone(plan_lanes.stale_reason(dict(inventory_cover={'cover_days': 60}), enabled=True))
        self.assertIsNone(plan_lanes.stale_reason(dict(inventory_cover={'cover_days': 60},
                                                       price_change={'days_since': 1}), enabled=True))

    # --- fix E: E1 (I1), a search the team invests in is never cut or paused automatically ---------------------
    LOGGED = dict(since='2026-10-05', role='Invest')

    def logged_plan(self, sqp, kw, shadow=False, **over):
        """'thank you cards' is in the product's invest log; its SQP record and its exact SKC keyword are `sqp` and `kw`."""
        cfg = product(invest_log={'thank you cards': self.LOGGED}, auto=dict(AUTO, enabled=not shadow), **over)
        queries = [q for q in QUERIES if q['Query'] != 'thank you cards'] + [sqp]
        keywords = [k for k in KEYWORDS if k['KeywordId'] != '1'] + [kw]
        return self.plan(cfg=cfg, queries=queries, keywords=keywords)

    def auto_rows(self):
        path = os.path.join(self.run_dir, 'payloads', 'auto', 'rows.json')
        return [rid for ids in read_rows(self.run_dir, 'auto').values() for rid in ids] if os.path.exists(path) else []

    def test_an_invested_search_that_slips_to_hold_is_cut_on_its_own_and_flagged(self):
        """I1's probe: the logged search's SQP index slips from about 1.2 to 1.0, so its role is Hold and the planner cuts
        its SKC keyword from $0.80 to $0.50 (-37.5%). From 2026-10-20 to 2026-10-22 that cut went to a person; since
        autonomous runs (decision 98) it applies on its own like any cut. It keeps its invested_search flag: log_invest
        steps the search down only when a person sent such a cut, or its stop-loss step-down went out."""
        for shadow in (False, True):
            with self.subTest(shadow=shadow):
                out = self.logged_plan(query('thank you cards', 1500, 600, 60, 40, 4),
                                       keyword('1', 'thank you cards', 'exact', SKC, 0.80, 40, 4, 30), shadow=shadow)
                term = next(t for t in out['terms'] if t['term'] == 'thank you cards')
                self.assertEqual((term['role'], term['index']), ('Hold', 1.0))
                cut = one(out, 'Bid change', keyword_id='1')
                self.assertEqual((cut['role'], cut['current'], cut['new']), ('Hold', 0.8, 0.5))
                self.assertEqual((cut['lane'], cut['lane_unlocked']), ('auto', 'auto'))
                self.assertEqual(cut['lane_reason'], 'cut from $0.80 to $0.50: a cut is never held back')
                self.assertIs(cut['invested_search'], True)
                self.assertEqual('Bid change:1' in self.auto_rows(), not shadow)
                self.assertEqual(human_review.row_levels(out)[out['changes'].index(cut)], 'owner')

    def test_a_pause_of_an_invested_search_applies_on_its_own(self):
        """At index 0.14 with no order on its keyword, the logged search's SKC keyword is paused, on its own since
        2026-10-22. The pause carries its plan role (Trim) and the invested_search flag."""
        out = self.logged_plan(query('thank you cards', 1500, 600, 60, 60, 0),
                               keyword('1', 'thank you cards', 'exact', SKC, 0.80, 40, 0, 30))
        pause = one(out, 'Pause keyword', keyword_id='1')
        self.assertEqual(pause['role'], 'Trim')
        # decision 182: the logged search slipped under 0.8 on 15+ clicks, so the pause is also its step-down
        self.assertEqual(pause['lane'], 'auto')
        self.assertIs(pause['stop_loss_step_down'], True)
        self.assertIn('decision 182', pause['lane_reason'])
        self.assertIs(pause['invested_search'], True)
        self.assertIn('Pause keyword:1', self.auto_rows())
        self.assertEqual(human_review.row_levels(out)[out['changes'].index(pause)], 'owner')

    def test_a_cut_on_a_search_nobody_invests_in_is_still_automatic(self):
        out = self.logged_plan(query('thank you cards', 1500, 600, 60, 40, 4),
                               keyword('1', 'thank you cards', 'exact', SKC, 0.80, 40, 4, 30))
        gold = one(out, 'Bid change', keyword_id='3')  # gold cards trails the market and was never invested in
        self.assertEqual((gold['lane'], gold.get('invested_search')), ('auto', None))
        self.assertIn('Bid change:3', self.auto_rows())

    def test_a_promotions_own_duplicate_pause_is_not_an_invested_cut(self):
        """The duplicate exact keyword a promotion pauses (its bundle) moves the search into its own campaign: it shares
        the promotion's lane (spec 5a), so a promotion can still be automatic."""
        out = self.plan()
        promo = one(out, 'New exact campaign', keyword='blank cards')
        pause = one(out, 'Pause keyword', keyword_id='2')
        self.assertEqual((promo['lane'], pause['lane']), ('auto', 'auto'))
        self.assertEqual(pause['role'], 'Invest')  # its plan role: blank cards is an Invest search
        self.assertNotIn('invested_search', pause)

    def test_every_planned_pause_carries_its_plan_role(self):
        irrelevant = keyword('9', 'random search', 'exact', STW, 0.40, 12, 0, 5)
        cfg = product(relevance=dict(negate_phrase={'random': 'not a card search'}))
        out = self.plan(cfg=cfg, keywords=KEYWORDS + [irrelevant], write_out=False)
        pauses = {x['keyword_id']: x for x in by_type(out, 'Pause keyword')}
        self.assertEqual(pauses['2']['role'], 'Invest')  # a promotion's duplicate: blank cards is an Invest search
        self.assertEqual(pauses['9']['role'], 'Negate')  # an irrelevant search

    def test_planned_invest_spend_counts_an_invested_search_that_is_no_longer_a_rank_search(self):
        """Its campaign keeps spending while its cut waits for a person, so Kim's running total (and the band) starts
        with its recent monthly ad spend: the search's 90-day ad spend / 3."""
        out = self.logged_plan(query('thank you cards', 1500, 600, 60, 40, 4),
                               keyword('1', 'thank you cards', 'exact', SKC, 0.80, 40, 4, 30))
        term = next(t for t in out['terms'] if t['term'] == 'thank you cards')
        self.assertNotIn('thank you cards', [r['keyword'] for r in out['rerank'] + out['rerank_held']])
        self.assertGreater(term['ad_spend'], 0)
        self.assertEqual(out['summary'][0]['planned_invest_month_start'], round(term['ad_spend'] / 3, 2))
        # without the invest log nothing is counted for it
        out = self.plan(queries=[q for q in QUERIES if q['Query'] != 'thank you cards']
                        + [query('thank you cards', 1500, 600, 60, 40, 4)],
                        keywords=[k for k in KEYWORDS if k['KeywordId'] != '1']
                        + [keyword('1', 'thank you cards', 'exact', SKC, 0.80, 40, 4, 30)], write_out=False)
        self.assertEqual(out['summary'][0]['planned_invest_month_start'], 0)

    def test_sqp_without_a_data_through_date_is_planned_on(self):
        out = self.plan(data_through=None, write_out=False)   # decision 172: its age is unknown, not a stop
        self.assertIsNone(out['summary'][0]['sqp_data_through'])
        self.assertIsNone(out['summary'][0]['sqp_age_days'])
        self.assertIsNone(out['summary'][0]['stale_reason'])

    def test_a_new_campaign_with_a_top_of_search_boost_is_written_at_the_standard(self):
        # decision 107 (2026-10-23): written at the standard 0% start instead of going to a person
        out = self.plan(shared=shared_config(recommendations=False), write_out=False)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['tos'], promo['tos_planned'], promo['lane']), (0, 50, 'auto'))
        self.assertEqual(promo['tos_bid'], promo['new'])
        self.assertIn('written at the standard budget and top of search (a new exact campaign starts at 0% top of search, '
                      'and this one would start at +50%)', promo['lane_reason'])
        self.assertEqual(one(out, 'Pause keyword', keyword_id='2')['lane'], 'auto')

    # --- the standing rank top-of-search policy (Kim, 2026-10-20) -----------------------------------------------------
    def test_standing_policy_makes_the_boosted_promotion_standard_and_automatic(self):
        out = self.plan(shared=shared_config(standing=True))
        self.assertIs(out['summary'][0]['shadow'], False)  # enabled mode
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['tos'], promo['budget'], promo['lane']), (50, 10, 'auto'))
        self.assertNotIn('placement_hold', promo)
        self.assertIn('fits the product', promo['lane_reason'])
        for member in (one(out, 'Pause keyword', keyword_id='2'),) + tuple(x for x in by_type(out, 'Negative exact') if x['keyword'] == 'blank cards'):
            self.assertEqual(member['lane'], 'auto')
        created = read_payloads(self.run_dir, 'auto')['1_new_campaigns.json']
        self.assertEqual([c['name'] for c in created], [promo['campaign']])
        self.assertEqual(created[0]['dynamicBidding']['placementBidding'], [dict(placement='PLACEMENT_TOP', percentage=50)])
        # the forecast now prices the boost the campaign will run at, so the band and Kim's level see the real spend
        flat = self.plan(shared=shared_config(), write_out=False)
        self.assertGreater(promo['modelled_spend_month'], one(flat, 'New exact campaign', keyword='blank cards')['modelled_spend_month'])

    def test_standing_policy_off_keeps_the_zero_start(self):
        out = self.plan(shared=shared_config(standing=False))
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['tos'], promo['lane'], promo['placement_hold']), (0, 'auto', True))
        # and with the economics review off too, the planner's +50 is not the standard start: it is written at 0% (decision 107)
        out = self.plan(shared=shared_config(recommendations=False, standing=False), write_out=False)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['tos'], promo['lane']), (0, 'auto'))
        self.assertIn('starts at 0% top of search', promo['lane_reason'])

    def test_standing_policy_with_the_economics_review_off_is_still_standard(self):
        out = self.plan(shared=shared_config(recommendations=False, standing=True), write_out=False)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['tos'], promo['lane']), (50, 'auto'))

    def test_a_boost_other_than_the_standing_policy_is_written_at_the_policy(self):
        shared = shared_config(standing=True)
        make_run(self.run_dir)
        out = planner.build(ASIN, product(), shared, self.run_dir, 'weekly', TODAY, now_utc=NOW, with_lanes=False)
        one(out, 'New exact campaign', keyword='blank cards')['tos'] = 80
        plan_lanes.assign(out, product(), shared, 'weekly', planner.load_lane_inputs(self.run_dir), TODAY, NOW)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['lane'], promo['tos'], promo['tos_planned']), ('auto', 50, 80))
        self.assertIn('+80%', promo['lane_reason'])
        self.assertIn('standing', promo['lane_reason'])
        self.assertEqual(one(out, 'Pause keyword', keyword_id='2')['lane'], 'auto')  # the bundle goes with it

    def test_promotion_odd_reads_the_standard_boost_from_the_policy(self):
        budgets = dict(CONFIG['budgets'], invest_per_day=10, prove_per_day=5)
        on = shared_config(standing=True)['placement']
        off = shared_config(standing=False)['placement']

        def row(ctype, role, tos, **extra):
            return dict(type=ctype, role=role, budget=10 if role == 'Invest' else 5, tos=tos, **extra)

        for ctype in ('New exact campaign', 'Reuse exact campaign'):
            with self.subTest(ctype):
                self.assertIsNone(plan_lanes.promotion_odd(row(ctype, 'Invest', 50), [], budgets, on))
                self.assertIsNone(plan_lanes.promotion_odd(row(ctype, 'Prove first', 30), [], budgets, on))
                self.assertIn('+30%', plan_lanes.promotion_odd(row(ctype, 'Invest', 30), [], budgets, on))
                self.assertIn('+80%', plan_lanes.promotion_odd(row(ctype, 'Invest', 80), [], budgets, on))
                self.assertIn('+50%', plan_lanes.promotion_odd(row(ctype, 'Prove first', 50), [], budgets, on))
                self.assertIsNotNone(plan_lanes.promotion_odd(row(ctype, 'Invest', 0), [], budgets, on))  # 0% is no longer the standard
                # flag off, or no placement settings given: +50 is odd and 0% is standard, as today
                for placement in (off, None):
                    self.assertIsNotNone(plan_lanes.promotion_odd(row(ctype, 'Invest', 50), [], budgets, placement))
        self.assertIsNone(plan_lanes.promotion_odd(row('New exact campaign', 'Invest', 0), [], budgets, off))
        self.assertIsNone(plan_lanes.promotion_odd(row('New exact campaign', 'Invest', 0), [], budgets))
        self.assertIsNone(plan_lanes.promotion_odd(row('Reuse exact campaign', 'Invest', 0, placement_hold=True), [], budgets, off))
        # a campaign the policy leaves alone (held) is judged as it was: a held reuse is standard whatever its live boost
        self.assertIsNone(plan_lanes.promotion_odd(row('Reuse exact campaign', 'Invest', 900, placement_hold=True), [], budgets, on))
        self.assertIsNone(plan_lanes.promotion_odd(row('New exact campaign', 'Invest', 0, placement_hold=True), [], budgets, on))
        # the budget row of the bundle is judged too
        member = row('Budget and top of search', 'Invest', 80)
        self.assertIn('+80%', plan_lanes.promotion_odd(row('Reuse exact campaign', 'Invest', 50), [member], budgets, on))
        self.assertIsNone(plan_lanes.promotion_odd(row('Reuse exact campaign', 'Invest', 50), [dict(member, tos=50)], budgets, on))
        # an unreadable percentage in the config is no standard at all
        self.assertIsNotNone(plan_lanes.promotion_odd(row('New exact campaign', 'Invest', 50), [], budgets, dict(on, invest_tos_pct='fifty')))

    def test_standing_policy_reuse_bundle_is_auto_and_keeps_the_live_others(self):
        queries = QUERIES + [query('note cards', 900, 400, 40, 20, 4)]
        terms = SEARCH_TERMS + [search_term('note cards', AUTO_CAMPAIGN, 15, 3, 9)]
        copy_kw = keyword('11', 'note cards', 'exact', STW, 0.40, 12, 2, 6)
        suggested = dict(SUGGESTED, **{'note cards': [0.45, 0.65, 0.85]})
        idle = campaign(IDLE_SKC, budget=5)
        idle['optimizations']['bidSettings']['bidAdjustments']['placementBidAdjustments'] += [
            dict(placement='PLACEMENT_REST_OF_SEARCH', percentage=15), dict(placement='PLACEMENT_PRODUCT_PAGE', percentage=20)]
        out = self.plan(shared=shared_config(standing=True), queries=queries, search_terms=terms, keywords=KEYWORDS + [copy_kw],
                        suggested=suggested, more_campaigns=[idle])
        reuse = one(out, 'Reuse exact campaign', keyword='note cards')
        self.assertEqual((reuse['lane'], reuse['tos'], reuse['tos_now'], reuse['budget']), ('auto', 50, 0, 10))
        self.assertNotIn('placement_hold', reuse)
        others = [dict(placement='PLACEMENT_REST_OF_SEARCH', percentage=15), dict(placement='PLACEMENT_PRODUCT_PAGE', percentage=20)]
        self.assertEqual(reuse['other_placements'], others)
        spec = next(r for r in read_payloads(self.run_dir, 'auto')['2_reuse_specs.json'] if r['campaign_id'] == IDS[IDLE_SKC][0])
        self.assertEqual((spec['tos'], spec['other_placements']), (50, others))

    def test_main_sets_the_policy_against_the_live_snapshot(self):
        # as test_main_prices_the_bands_after_the_placement_refresh, with the standing policy on: the snapshot shows the
        # invest campaign at +100%, the policy is +50%, and main() re-prices the re-rank at the policy, not the live boost
        make_run(self.run_dir)
        cid = IDS[SKC][0]
        write(os.path.join(self.run_dir, 'campaigns.json'),
              dict(items=[campaign(STW), campaign(AUTO_CAMPAIGN), campaign(BROAD), campaign(LOW), campaign(SKC, budget=8, tos=50), campaign(PT)]))
        row = dict(asin=ASIN, campaignId=cid, placement='Top of Search on-Amazon')
        for suffix in ('30', '90', '_recent'):
            row.update({k + suffix: v for k, v in dict(clicks=60, orders=12, spend=24, sales=120).items()})
        write(os.path.join(self.run_dir, 'placement_inputs.json'),
              dict(asin=ASIN, complete=True, as_of='2026-10-18', retrieved_at='2026-10-18T18:00:00+08:00',
                   windows={'30d': ['2026-09-04', '2026-10-03'], '90d': ['2026-07-06', '2026-10-03'],
                            'recent': ['2026-09-18', '2026-10-17']},
                   campaigns=[campaign(SKC, budget=8, tos=100)], live_asins={cid: [ASIN]}, rows=[row]))
        skill = os.path.join(self.tmp, 'skill')
        os.makedirs(os.path.join(skill, 'data', 'asins'))
        write(os.path.join(skill, 'config.json'), shared_config(standing=True))
        write(os.path.join(skill, 'data', 'asins', f'{ASIN}.json'), product())
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--skill', skill, '--today', TODAY]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), without_mid():
            planner.main()
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            saved = json.load(fh)
        budget = next(x for x in saved['changes'] if x['type'] == 'Budget and top of search')
        self.assertEqual((budget['tos'], budget['tos_now'], budget['budget_now'], budget['budget']), (50, 100, 8, 10))
        self.assertNotIn('placement_hold', budget)
        self.assertEqual(next(r for r in saved['rerank'] if r['keyword'] == 'thank you cards')['tos'], 50)
        promo = next(x for x in saved['changes'] if x['type'] == 'New exact campaign')
        self.assertEqual(promo['tos'], 50)

    # --- a live rank campaign's top of search set to the policy is not Needs human (Kim, 2026-10-20) -----------------
    def policy_plan(self, live_budget=10, live_tos=0, standing=True, cfg=None, write_out=True):
        """The fixture with its live 'thank you cards' exact campaign at `live_budget` and `live_tos`: the planner builds a
        'Budget and top of search' row for it (the policy is +50)."""
        make_run(self.run_dir)
        write(os.path.join(self.run_dir, 'campaigns.json'),
              dict(items=[campaign(STW), campaign(AUTO_CAMPAIGN), campaign(BROAD), campaign(LOW),
                          campaign(SKC, budget=live_budget, tos=live_tos), campaign(PT)]))
        shared = shared_config(standing=standing)
        out = planner.build(ASIN, cfg or product(), shared, self.run_dir, 'weekly', TODAY, now_utc=NOW)
        if write_out:
            planner.write_outputs(self.run_dir, out, shared, ASIN)
        return out

    def levels(self, out):
        return dict(zip([x['row_id'] for x in out['changes']], human_review.row_levels(out)))

    def test_a_policy_only_top_of_search_row_on_a_live_invest_campaign_goes_auto(self):
        out = self.policy_plan()
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertIs(out['summary'][0]['shadow'], False)  # enabled mode
        self.assertEqual((row['role'], row['budget_now'], row['budget'], row['tos_now'], row['tos']), ('Invest', 10, 10, 0, 50))
        self.assertIs(row['policy_tos_only'], True)
        self.assertNotIn('placement_hold', row)
        self.assertEqual(row['lane'], 'auto')
        self.assertIn('enough proof for Invest', row['lane_reason'])
        self.assertNotIn('past_kim_level', row)   # no money level since 2026-10-22 (decision 99)
        self.assertGreater(row['modelled_spend_month'], 0)
        auto = read_payloads(self.run_dir, 'auto')['5_campaign_updates.json']
        written = next(r for r in auto if r['campaignId'] == IDS[SKC][0])
        self.assertEqual(written['budget'], dict(budget=10, budgetType='DAILY'))
        self.assertEqual(written['dynamicBidding']['placementBidding'], [dict(placement='PLACEMENT_TOP', percentage=50)])
        self.assertIn(row['row_id'], read_rows(self.run_dir, 'auto')['5_campaign_updates.json'])
        # the funnel negative for the same search applies on its own too (since 2026-10-22)
        self.assertEqual(one(out, 'Negative exact', keyword='thank you cards')['lane'], 'auto')

    def test_the_same_row_with_a_budget_change_to_the_standard_applies_on_its_own(self):
        # autonomous runs (2026-10-22): a budget and top-of-search row at its role's standard budget ($10 Invest) and the
        # standing policy applies on its own; until then a budget change was always a person's
        out = self.policy_plan(live_budget=8)
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertEqual((row['budget_now'], row['budget'], row['tos']), (8, 10, 50))
        self.assertFalse(row.get('policy_tos_only'))
        self.assertEqual((row['lane'], row['lane_reason']), ('auto', "its role's standard budget and top of search (rulebook 7.5)"))
        self.assertIn(row['row_id'], [rid for rows in read_rows(self.run_dir, 'auto').values() for rid in rows])

    def test_a_budget_override_is_the_standard_for_its_search(self):
        # decision 107 (2026-10-23): a budget a person set for the search (budget_overrides, here $15) is its standard, so
        # the row applies on its own; until then it went to a person
        out = self.policy_plan(live_budget=8, cfg=product(budget_overrides={'thank you cards': 15}))
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertEqual((row['budget_now'], row['budget'], row['lane']), (8, 15, 'auto'))
        self.assertNotIn('budget_planned', row)

    def test_a_budget_row_at_any_other_budget_is_written_at_the_standard(self):
        shared = shared_config(standing=True)
        make_run(self.run_dir)
        write(os.path.join(self.run_dir, 'campaigns.json'),
              dict(items=[campaign(STW), campaign(AUTO_CAMPAIGN), campaign(BROAD), campaign(LOW), campaign(SKC, budget=8, tos=0), campaign(PT)]))
        out = planner.build(ASIN, product(), shared, self.run_dir, 'weekly', TODAY, now_utc=NOW, with_lanes=False)
        one(out, 'Budget and top of search', keyword='thank you cards')['budget'] = 15
        plan_lanes.assign(out, product(), shared, 'weekly', planner.load_lane_inputs(self.run_dir), TODAY, NOW)
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertEqual((row['budget'], row['budget_planned'], row['lane']), (10, 15, 'auto'))
        self.assertIn('it has a budget of $15/day, not the standard $10/day for Invest', row['lane_reason'])

    def test_with_the_flag_off_the_row_holds_the_live_boost_and_applies(self):
        out = self.policy_plan(standing=False)
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertFalse(row.get('policy_tos_only'))
        self.assertTrue(row['placement_hold'])  # held exactly as before: no top-of-search write, the budget only
        self.assertEqual(row['tos'], 0)
        self.assertEqual(row['lane'], 'auto')  # a budget-only write at the standard budget (2026-10-22)

    def test_a_policy_only_row_with_any_other_top_of_search_is_written_at_the_policy(self):
        shared = shared_config(standing=True)
        make_run(self.run_dir)
        write(os.path.join(self.run_dir, 'campaigns.json'),
              dict(items=[campaign(STW), campaign(AUTO_CAMPAIGN), campaign(BROAD), campaign(LOW), campaign(SKC, budget=10, tos=0), campaign(PT)]))
        out = planner.build(ASIN, product(), shared, self.run_dir, 'weekly', TODAY, now_utc=NOW, with_lanes=False)
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertIs(row['policy_tos_only'], True)
        row['tos'] = 80  # not the policy's +50, whatever the marker says
        plan_lanes.assign(out, product(), shared, 'weekly', planner.load_lane_inputs(self.run_dir), TODAY, NOW)
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertEqual((row['lane'], row['tos'], row['tos_planned']), ('auto', 50, 80))   # decision 107
        self.assertFalse(row['policy_tos_only'])

    def test_a_policy_only_row_has_no_money_level(self):
        # until 2026-10-22 a guide of $1 a month made it Kim's; since decision 99 the guide only flags the summary
        out = self.policy_plan(cfg=product(auto=dict(AUTO, invest_guide_month=1)), write_out=False)
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertEqual(row['lane'], 'auto')
        self.assertEqual(self.levels(out)[row['row_id']], 'owner')
        self.assertIs(out['summary'][0]['above_invest_guide'], True)

    def test_a_policy_only_row_and_a_budget_change_are_the_owners(self):
        # Kim, 2026-10-22: 'Budget and top of search' rows are the book owner's (a budget change was Lee's before)
        out = self.policy_plan(write_out=False)
        self.assertEqual(self.levels(out)[one(out, 'Budget and top of search', keyword='thank you cards')['row_id']], 'owner')
        out = self.policy_plan(live_budget=8, write_out=False)
        self.assertEqual(self.levels(out)[one(out, 'Budget and top of search', keyword='thank you cards')['row_id']], 'owner')
        # a product still onboarding is judged as usual since 2026-10-22, and the row stays the owner's
        out = self.policy_plan(cfg=product(registry=dict(bid_owner='AI', stage='onboarding', owner_since='2026-10-18')), write_out=False)
        row = one(out, 'Budget and top of search', keyword='thank you cards')
        self.assertEqual(row['lane'], 'auto')
        self.assertEqual(self.levels(out)[row['row_id']], 'owner')

    def test_a_policy_only_row_shows_the_numbers_an_approval_must_have_seen(self):
        # the Bids card sends what it shows as `seen`, and dashboard.py compares it with the plan row: the card's row must
        # carry the row's modelled monthly spend, or every approval of it would read as changed since the plan
        import dashboard
        out = self.policy_plan(cfg=product(auto=dict(AUTO, enabled=False)), write_out=False)  # shadow: every row is on the item
        change = one(out, 'Budget and top of search', keyword='thank you cards')
        item = human_review.propose_bids(out, TODAY)
        row = next(r for r in item['rows'] if r['row_id'] == change['row_id'])
        self.assertEqual((row['budget_now'], row['budget'], row['tos_now'], row['tos']), (10, 10, 0, 50))
        self.assertEqual(row['modelled_spend_month'], change['modelled_spend_month'])
        self.assertGreater(row['modelled_spend_month'], 0)
        self.assertEqual(dashboard.shown(row), dashboard.shown(change))
        self.assertEqual(row['approval_required'], 'owner')

    def test_a_budget_override_promotion_goes_out_at_its_override(self):
        # decision 107 (2026-10-23): the product file's override is the search's standard budget
        out = self.plan(cfg=product(budget_overrides={'blank cards': 15}), write_out=False)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['lane'], promo['budget']), ('auto', 15))
        self.assertNotIn('written at the standard', promo['lane_reason'])

    def test_a_promotion_at_any_other_budget_is_written_at_the_standard(self):
        make_run(self.run_dir)
        out = planner.build(ASIN, product(), shared_config(), self.run_dir, 'weekly', TODAY, now_utc=NOW, with_lanes=False)
        one(out, 'New exact campaign', keyword='blank cards')['budget'] = 15
        plan_lanes.assign(out, product(), shared_config(), 'weekly', planner.load_lane_inputs(self.run_dir), TODAY, NOW)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((promo['lane'], promo['budget'], promo['budget_planned']), ('auto', 10, 15))
        self.assertIn('not the standard $10/day for Invest', promo['lane_reason'])

    def test_a_row_on_an_overnight_test_copy_is_held_whatever_its_lane(self):
        # 2026-11-04: the overnight test's own thread sets its "ON80 |" / "ON50 |" copies' bids; the AI run leaves them
        make_run(self.run_dir)
        shared = shared_config()
        shared['placement'].setdefault('shape', {})['experiment_name_markers'] = ['ON80 |', 'ON50 |']
        out = planner.build(ASIN, product(), shared, self.run_dir, 'weekly', TODAY, now_utc=NOW, with_lanes=False)
        rows = [x for x in out['changes'] if x['type'] == 'Bid change']
        self.assertTrue(rows)
        rows[0]['campaign'] = 'ON50 | ' + (rows[0].get('campaign') or 'Cards - Broad')
        plan_lanes.assign(out, product(), shared, 'weekly', planner.load_lane_inputs(self.run_dir), TODAY, NOW)
        held = rows[0]
        self.assertEqual((held['lane'], held['lane_unlocked']), ('monitor', 'monitor'))
        self.assertIn('ON50 | copy', held['experiment_hold'])
        self.assertNotIn('ownership_scope_blocked', held)
        self.assertEqual(out['summary'][0]['experiment_holds'], {held['row_id']: held['experiment_hold']})
        for other in rows[1:]:
            self.assertNotIn('experiment_hold', other)

    def test_experiment_rows_reads_the_markers_case_blind(self):
        shared = dict(placement=dict(shape=dict(experiment_name_markers=['ON80 |', 'ON50 |'])))
        rows = [dict(row_id='a', campaign='on80 | Cards - Exact'), dict(row_id='b', campaign='Cards - Exact'),
                dict(row_id='c', campaign='ON50 | Cards - Auto'), dict(row_id='d')]
        self.assertEqual(sorted(plan_lanes.experiment_rows(rows, shared)), ['a', 'c'])
        self.assertEqual(plan_lanes.experiment_rows(rows, {}), {})

    def test_rows_carry_ids_evidence_and_the_plan_carries_bands(self):
        out = self.plan()
        ids = {x['row_id'] for x in out['changes']}
        for expected in ('New exact campaign:::blank cards', 'Bid change:4', 'Pause keyword:2', 'Pause target:301',
                         'Target bid change:302', 'Negative exact:101:201:blank cards',
                         'Negative exact:102:202:blank cards', 'Negative exact:102:202:thank you cards'):
            self.assertIn(expected, ids)
        cut = one(out, 'Bid change', keyword_id='3')
        self.assertIn('sure it converts under 0.8x the market', cut['confidence_text'])
        self.assertGreater(cut['confidence'], 0.5)
        target_cut = one(out, 'Pause target', target_id='301')
        self.assertIn("the product's ad average", target_cut['confidence_text'])
        self.assertEqual(target_cut['baseline_cvr'], out['summary'][0]['asin_ad_cvr'])
        raise_ = one(out, 'Bid change', keyword_id='1')
        self.assertIn('sure it beats the market', raise_['confidence_text'])
        self.assertGreater(raise_['opportunity'], 0)
        for x in out['changes']:
            for field in ('lane', 'lane_reason', 'confidence', 'confidence_text', 'opportunity', 'row_id'):
                self.assertIn(field, x)
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            saved = json.load(fh)
        self.assertEqual(set(saved['bands']), {r['keyword'] for r in out['rerank']})
        self.assertAlmostEqual(saved['band_product_month'], sum(saved['bands'].values()), places=2)
        self.assertIn('lane', saved['changes'][0])

    def test_the_bands_start_net_of_existing_invest_spend(self):
        out = self.plan(write_out=False)
        spend = {r['keyword']: r['spend'] for r in out['rerank']}
        self.assertEqual(out['bands'], {k: float(v) for k, v in spend.items()})  # no search loses $60 a month here
        promo = one(out, 'New exact campaign', keyword='blank cards')
        # 'thank you cards' already owns its campaign, so its spend is planned before the promotion is judged
        self.assertIn(f"of ${out['band_product_month'] - spend['thank you cards']:.2f} left", promo['lane_reason'])

    def test_every_row_id_in_a_build_is_unique(self):
        # two funnel negatives in one campaign (the 'blank cards' search in two of its ad groups, and 'thank you cards')
        terms = SEARCH_TERMS + [search_term('blank cards', AUTO_CAMPAIGN, 4, 0, 2, ad_group='209')]
        out = self.plan(search_terms=terms, write_out=False)
        ids = [x['row_id'] for x in out['changes']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(i.startswith('Negative exact:102:') for i in ids), 3)
        self.assertIn('Negative exact:102:209:blank cards', ids)

    def test_rows_that_still_collide_get_a_numbered_suffix_in_plan_order(self):
        rows = [dict(type='Listing price'), dict(type='Bid change', keyword_id='5'), dict(type='Listing price'),
                dict(type='Listing price'), dict(type='Negative exact', campaign_id='None', ad_group_id='9', keyword='Blank Cards')]
        plan_lanes.assign_row_ids(rows)
        self.assertEqual([x['row_id'] for x in rows], ['Listing price:::', 'Bid change:5', 'Listing price::::2',
                                                       'Listing price::::3', 'Negative exact::9:blank cards'])

    def test_colliding_rows_take_a_suffix_from_a_stable_field_whatever_the_plan_order(self):
        """A8 (M4): a lock on a suffixed row_id must land on the same row next week, so the suffix comes from the match type,
        then the ad group, then the campaign, never from where the row happens to sit in the plan."""
        def rows():
            return [dict(type='Pause keyword', campaign_id='101', ad_group_id='201', keyword='blank cards', match='exact'),
                    dict(type='Pause keyword', campaign_id='101', ad_group_id='201', keyword='blank cards', match='phrase')]
        forward, flipped = rows(), rows()[::-1]
        plan_lanes.assign_row_ids(forward)
        plan_lanes.assign_row_ids(flipped)
        self.assertEqual({x['match']: x['row_id'] for x in forward}, {x['match']: x['row_id'] for x in flipped})
        self.assertEqual({x['match']: x['row_id'] for x in forward},
                         {'exact': 'Pause keyword:101:201:blank cards:exact', 'phrase': 'Pause keyword:101:201:blank cards:phrase'})

        def by_group():  # the same match, so the ad group tells them apart; the campaign only when that is the same too
            return [dict(type='Bid change', keyword_id='5', match='exact', ad_group_id='A2', campaign_id='C1'),
                    dict(type='Bid change', keyword_id='5', match='exact', ad_group_id='A1', campaign_id='C1'),
                    dict(type='Bid change', keyword_id='5', match='phrase', ad_group_id='A1', campaign_id='C1'),
                    dict(type='Target bid change', target_id='9', ad_group_id='A1', campaign_id='C2'),
                    dict(type='Target bid change', target_id='9', ad_group_id='A1', campaign_id='C1')]
        for order in (by_group(), by_group()[::-1]):
            plan_lanes.assign_row_ids(order)
            self.assertEqual(sorted(x['row_id'] for x in order),
                             ['Bid change:5:exact:A1', 'Bid change:5:exact:A2', 'Bid change:5:phrase',
                              'Target bid change:9:C1', 'Target bid change:9:C2'])
        lone = [dict(type='Bid change', keyword_id='5', match='exact')]
        plan_lanes.assign_row_ids(lone)
        self.assertEqual(lone[0]['row_id'], 'Bid change:5')  # no collision, no suffix

    def test_a_decision_on_one_sibling_negative_locks_only_that_row(self):
        decisions = [dict(id='Negative exact:102:202:thank you cards', what='decline', by='Lee', until='2026-11-16')]
        out = self.plan(cfg=product(decisions=decisions), write_out=False)
        decided = one(out, 'Negative exact', row_id='Negative exact:102:202:thank you cards')
        self.assertEqual(decided['lane_reason'], 'decided by Lee on 2026-10-19 (declined this row); it holds until '
                                                 '2026-11-16, so a person decides')
        sibling = one(out, 'Negative exact', row_id='Negative exact:102:202:blank cards')
        self.assertEqual(sibling['lane'], 'auto')  # same campaign and ad group, another search's bundle: untouched
        self.assertEqual(one(out, 'New exact campaign', keyword='blank cards')['lane'], 'auto')
        self.assertEqual(one(out, 'Bid change', keyword_id='1')['lane'], 'auto')  # nor its own search's other rows

    def test_a_locked_bundle_member_sends_the_whole_bundle_to_a_person(self):
        decisions = [dict(id='Pause keyword:2', what='decline', by='Kim', until='2026-11-16')]
        out = self.plan(cfg=product(decisions=decisions), write_out=False)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual(promo['lane'], 'human')
        self.assertIn('pause of the duplicate keyword', promo['lane_reason'])
        self.assertIn('is locked: decided by Kim on 2026-10-19 (declined this row); it holds until 2026-11-16',
                      promo['lane_reason'])
        for member in [one(out, 'Pause keyword', keyword_id='2')] + [x for x in by_type(out, 'Negative exact')
                                                                     if x['keyword'] == 'blank cards']:
            self.assertEqual(member['lane'], 'human')
            self.assertTrue(member['lane_reason'].startswith('part of the promotion of blank cards: '))

    def test_promotions_go_biggest_opportunity_first(self):
        # 'zebra cards' comes after 'blank cards' in the plan but is the bigger prize, so it is judged first and its spend
        # is taken from the product's band first (the band is information only since decision 100; until then a band with
        # room for one of them sent the smaller prize to a person, and Kim's $600 level did the same)
        queries = QUERIES + [query('zebra cards', 4000, 1600, 160, 40, 8)]
        suggested = dict(SUGGESTED, **{'zebra cards': [0.55, 0.70, 0.90]})
        first = self.plan(queries=queries, suggested=suggested, write_out=False)
        names = [x['keyword'] for x in by_type(first, 'New exact campaign')]
        self.assertEqual(names, ['blank cards', 'zebra cards'])
        zebra, blank = (one(first, 'New exact campaign', keyword=k) for k in ('zebra cards', 'blank cards'))
        self.assertGreater(zebra['opportunity'], blank['opportunity'])
        self.assertEqual((zebra['lane'], blank['lane']), ('auto', 'auto'))
        # the band has room for both here, and zebra cards, judged first, takes its share of it first
        room = first['band_product_month'] - first['summary'][0]['planned_invest_month_start']
        self.assertGreaterEqual(room, zebra['modelled_spend_month'] + blank['modelled_spend_month'])
        self.assertIn(f"{zebra['modelled_spend_month']:.2f} of ${room:.2f} left", zebra['lane_reason'])

    def test_an_incomplete_auto_block_sends_everything_to_a_person(self):
        shared = shared_config()
        shared['auto'] = {'enabled': True}
        out = self.plan(cfg=product(auto={'enabled': True}), shared=shared, write_out=False)
        self.assertIs(out['summary'][0]['shadow'], False)
        for x in out['changes']:
            self.assertEqual(x['lane'], 'human')
            self.assertIn('the settings for automatic changes are incomplete', x['lane_reason'])
            self.assertIn('max_raises', x['lane_reason'])
        self.assertEqual(out['bands'], {})

    def test_a_reuse_bundle_is_auto_together(self):
        queries = QUERIES + [query('note cards', 900, 400, 40, 20, 4)]
        terms = SEARCH_TERMS + [search_term('note cards', AUTO_CAMPAIGN, 15, 3, 9)]
        copy_kw = keyword('11', 'note cards', 'exact', STW, 0.40, 12, 2, 6)  # an exact campaign already owns it
        suggested = dict(SUGGESTED, **{'note cards': [0.45, 0.65, 0.85]})
        out = self.plan(queries=queries, search_terms=terms, keywords=KEYWORDS + [copy_kw], suggested=suggested,
                        more_campaigns=[campaign(IDLE_SKC, budget=5)])
        reuse = one(out, 'Reuse exact campaign', keyword='note cards')
        self.assertEqual((reuse['lane'], reuse['budget'], reuse['placement_hold']), ('auto', 10, True))
        pause = one(out, 'Pause keyword', keyword_id='11')
        negative = one(out, 'Negative exact', keyword='note cards')
        for member in (pause, negative):
            self.assertEqual(member['lane'], 'auto')
            self.assertTrue(member['lane_reason'].startswith('part of the promotion of note cards: '))
        auto = read_payloads(self.run_dir, 'auto')
        self.assertEqual([r['campaign_id'] for r in auto['2_reuse_specs.json']], ['107'])
        self.assertIn('11', [p['keywordId'] for p in auto['3_pauses.json']])
        self.assertIn('note cards', [n['keywordText'] for n in auto['6_negatives_01.json']])

    # --- A5 (I2): auto/ and review/ hold only rows that can still go out; rows.json names the row behind each payload --
    def test_locked_rows_are_held_out_of_auto_and_review(self):
        decisions = [dict(id='Bid change:3', what='decline', by='Lee', until='2026-11-16', direction='down'),
                     dict(id='Bid change:5', what='decline', by='Lee', until='2026-11-16'),
                     dict(id='Pause target:301', what='decline', by='Kim', until='2026-11-16', direction='pause')]
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                out = self.plan(cfg=product(auto=dict(AUTO, enabled=enabled), decisions=decisions))
                auto, review = read_payloads(self.run_dir, 'auto'), read_payloads(self.run_dir, 'review')
                held = read_payloads(self.run_dir, 'held')
                for folder in (auto, review):
                    text = json.dumps(folder)
                    for kid in ('"3"', '"5"', '"301"'):
                        self.assertNotIn(kid, text)  # a person refused these: nothing can send them by mistake
                # locked rows, and the monitor row 6 (B10: held in both modes)
                self.assertEqual(held['4_bids_01.json'], [dict(type='sp_keywords', keywordId='3', bid=0.1),
                                                          dict(type='sp_keywords', keywordId='5', bid=0.25),
                                                          dict(type='sp_keywords', keywordId='6', bid=0.5)])
                self.assertEqual(held['9_target_pauses.json'], [dict(type='sp_targets', targetId='301', state='PAUSED')])
                self.assertEqual(sorted(held), ['4_bids_01.json', '9_target_pauses.json'])
                self.assertEqual(read_rows(self.run_dir, 'held'), {'4_bids_01.json': ['Bid change:3', 'Bid change:5', 'Bid change:6'],
                                                                   '9_target_pauses.json': ['Pause target:301']})
                self.assertEqual({x['row_id'] for x in out['changes'] if x.get('locked_until')},
                                 {'Bid change:3', 'Bid change:5', 'Pause target:301'})
        self.plan()  # a later plan of the same folder with no locks leaves only the monitor row held
        self.assertEqual(read_payloads(self.run_dir, 'held'), {'4_bids_01.json': [dict(type='sp_keywords', keywordId='6', bid=0.5)]})

    def test_monitor_rows_are_held_in_both_modes(self):
        """B10: a row the planner holds until the next run is in held/, never in auto/ or review/, enabled or shadow."""
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                out = self.plan(cfg=product(auto=dict(AUTO, enabled=enabled)))
                monitor = [x['row_id'] for x in out['changes'] if x['lane'] == 'monitor']
                self.assertEqual(monitor, ['Bid change:6'])
                held = read_rows(self.run_dir, 'held')
                self.assertEqual(held, {'4_bids_01.json': monitor})
                for folder in ('auto', 'review'):
                    if os.listdir(os.path.join(self.run_dir, 'payloads', folder)):
                        ids = [rid for rows in read_rows(self.run_dir, folder).values() for rid in rows]
                        self.assertNotIn('Bid change:6', ids, folder)

    def test_rows_json_names_the_row_behind_every_payload_row(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                out = self.plan(cfg=product(auto=dict(AUTO, enabled=enabled)))
                by_id = {x['row_id']: x for x in out['changes']}
                for folder in ('auto', 'review'):
                    files = read_payloads(self.run_dir, folder)
                    if not files:
                        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', folder, 'rows.json')))
                        continue
                    rows = read_rows(self.run_dir, folder)
                    self.assertEqual(set(rows), set(files))
                    for name, payload in files.items():
                        self.assertEqual(len(rows[name]), len(payload), (folder, name))
                        for rid, prow in zip(rows[name], payload):
                            # the row named is the one that writes this payload row, as written
                            own = dict(planner.payload_files([planner.as_written(by_id[rid])], shared_config(), ASIN))
                            self.assertIn(prow, own[name], (folder, name, rid))
        auto = read_rows(self.run_dir, 'review')  # shadow: the new campaign is named in both of its files
        self.assertEqual(auto['1_new_campaigns.json'], ['New exact campaign:::blank cards'])
        self.assertEqual(auto['1b_new_skc_specs.json'], ['New exact campaign:::blank cards'])

    def test_payload_row_ids_follow_merged_and_skipped_rows(self):
        shared = shared_config()
        rows = [dict(type='Bid change', row_id='Bid change:5', keyword_id='5', new=0.4),
                dict(type='Bid change', row_id='Bid change:5:phrase', keyword_id='5', new=0.6),  # same keyword: one write
                dict(type='New SB video campaign', row_id='New SB video campaign:::a', campaign='SB 1', keyword='a', new=0.5, budget=10),
                dict(type='New SB video campaign', row_id='New SB video campaign:::b', campaign='SB 1', keyword='b', new=0.6, budget=10),
                dict(type='Harvest default bid', row_id='Harvest default bid::9:', ad_group_id='9', new=0.3),
                dict(type='Budget and top of search', row_id='Budget and top of search:7::', campaign_id='7', budget=10,
                     placement_hold=True)]
        files = dict(planner.payload_files(rows, shared, ASIN))
        ids = planner.payload_row_ids(rows, shared, ASIN)
        self.assertEqual(set(ids), set(files))
        self.assertEqual(ids['4_bids_01.json'], ['Bid change:5'])
        self.assertEqual(len(files['7_sb_new_campaigns.json']), 1)  # one build spec holds both keywords
        self.assertEqual(ids['7_sb_new_campaigns.json'], ['New SB video campaign:::a', 'New SB video campaign:::b'])
        self.assertEqual(ids['5_campaign_updates.json'], ['Budget and top of search:7::', 'Harvest default bid::9:'])

    def test_planning_twice_leaves_no_stale_auto_payloads(self):
        self.plan()
        self.assertTrue(os.listdir(os.path.join(self.run_dir, 'payloads', 'auto')))
        self.plan(cfg=product(auto=dict(AUTO, enabled=False)))
        self.assertEqual(os.listdir(os.path.join(self.run_dir, 'payloads', 'auto')), [])

    # --- locked_until: which rows a person has already decided (Task 6a, R2) -----------------------------------
    def locked(self, out):
        return {x['row_id']: x['locked_until'] for x in out['changes'] if 'locked_until' in x}

    def test_locked_until_is_stamped_on_every_row_a_lock_holds(self):
        decisions = [dict(id='Bid change:5', what='decline', by='Lee', until='2026-11-16'),
                     dict(id='Bid change:3', what='approve', by='Lee', until='2026-10-18'),  # expired
                     dict(id='4', what='decline', by='Kim', until='2026-12-01T00:00:00Z')]     # a bare keyword id
        out = self.plan(cfg=product(decisions=decisions), write_out=False)
        self.assertEqual(self.locked(out), {'Bid change:5': '2026-11-16', 'Bid change:4': '2026-12-01'})
        self.assertNotIn('locked_until', one(out, 'Bid change', keyword_id='3'))  # an expired lock holds nothing
        clean = self.plan(write_out=False)
        self.assertEqual(self.locked(clean), {})  # no lock, no key

    def test_a_lock_without_a_readable_date_is_stamped_as_written(self):
        decisions = [dict(id='Bid change:5', what='decline', by='Lee', until='further notice')]
        rows = [dict(keyword='cards', status='proposed_not_applied')]  # a rank experiment waiting for a person
        out = self.plan(cfg=product(decisions=decisions, proposed_rank_experiments=dict(rows=rows)), write_out=False)
        self.assertEqual(self.locked(out), {'Bid change:5': 'further notice', 'Bid change:4': 'further notice'})

    def test_a_locked_member_stamps_the_whole_bundle_it_holds(self):
        decisions = [dict(id='Pause keyword:2', what='decline', by='Kim', until='2026-11-16')]
        out = self.plan(cfg=product(decisions=decisions), write_out=False)
        bundle = ['New exact campaign:::blank cards', 'Pause keyword:2', 'Negative exact:101:201:blank cards',
                  'Negative exact:102:202:blank cards']
        self.assertEqual(self.locked(out), {rid: '2026-11-16' for rid in bundle})
        self.assertNotIn('locked_until', one(out, 'Negative exact', keyword='thank you cards'))
        self.assertNotIn('locked_until', one(out, 'Bid change', keyword_id='1'))

    def test_a_locked_promotion_stamps_its_members(self):
        decisions = [dict(id='New exact campaign:::blank cards', what='decline', by='Lee', until='2026-11-16')]
        out = self.plan(cfg=product(decisions=decisions), write_out=False)
        self.assertEqual(set(self.locked(out)), {'New exact campaign:::blank cards', 'Pause keyword:2',
                                                 'Negative exact:101:201:blank cards', 'Negative exact:102:202:blank cards'})
        self.assertEqual(set(self.locked(out).values()), {'2026-11-16'})

    def test_a_row_keeps_the_longer_of_its_own_lock_and_its_bundles(self):
        own = 'Negative exact:101:201:blank cards'
        decisions = [dict(id='Pause keyword:2', what='decline', by='Kim', until='2026-11-16'),
                     dict(id=own, what='decline', by='Kim', until='2026-12-14')]
        locked = self.locked(self.plan(cfg=product(decisions=decisions), write_out=False))
        self.assertEqual(len(locked), 4)  # the whole bundle
        self.assertEqual(locked[own], '2026-12-14')
        self.assertEqual({v for k, v in locked.items() if k != own}, {'2026-11-16'})

    def test_a_member_locked_inside_a_promotion_held_for_another_reason_is_stamped_alone(self):
        # the promotion is short of the ladder, so it is held anyway (a person's call until decision 107, a short band until
        # decision 100); only the row a person decided is locked
        decisions = [dict(id='Pause keyword:2', what='decline', by='Kim', until='2026-11-16')]
        out = self.plan(cfg=product(auto=dict(AUTO, invest_orders=100, prove_orders=100), decisions=decisions),
                        write_out=False)
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual(promo['lane'], 'monitor')
        self.assertIn('not yet, the next run judges it again', promo['lane_reason'])
        self.assertEqual(self.locked(out), {'Pause keyword:2': '2026-11-16'})

    def test_locked_rows_are_stamped_when_the_auto_settings_are_incomplete(self):
        shared = shared_config()
        shared['auto'] = {'enabled': True}
        decisions = [dict(id='Bid change:5', what='decline', by='Lee', until='2026-11-16')]
        out = self.plan(cfg=product(auto={'enabled': True}, decisions=decisions), shared=shared, write_out=False)
        self.assertIn('incomplete', one(out, 'Bid change', keyword_id='5')['lane_reason'])
        self.assertEqual(self.locked(out), {'Bid change:5': '2026-11-16'})
        self.assertEqual({x['lane_unlocked'] for x in out['changes']}, {'human'})  # no lock made them human

    # --- A3 (I3): locks know who decided, when and which way, and every row records its lane without them -----------
    def test_lock_table_reads_who_when_and_which_way(self):
        decisions = [dict(id='Bid change:4', what='approve', by=' Lee ', until='2026-11-16', direction='up'),
                     dict(id='Bid change:3', what='decline', by='Kim', until='2026-11-17', on='2026-10-20', direction='down'),
                     dict(id='Bid change:5', what='decline', by='Kim', until='2026-11-16'),           # an older entry
                     dict(id='Bid change:6', what='decline', by='Kim', until='2026-11-16', direction='sideways'),
                     dict(id='Bid change:7', what='decline', until='further notice')]                  # no by, no date
        locks, problem = plan_lanes.lock_table(dict(decisions=decisions), lock_weeks=4)
        self.assertIsNone(problem)
        key = lanes.lock_key
        approve = locks[key('Bid change:4')]
        self.assertEqual({k: approve[k] for k in ('until', 'what', 'by', 'on', 'direction')},
                         dict(until='2026-11-16', what='approve', by='Lee', on='2026-10-19', direction='up'))
        self.assertIs(locks[key('4')], approve)  # the keyword id holds with the same lock
        self.assertEqual(approve['reason'], 'decided by Lee on 2026-10-19 (approved a raise, and this goes the other way); '
                                            'it holds until 2026-11-16, so a person decides')
        decline = locks[key('Bid change:3')]
        self.assertEqual((decline['on'], decline['direction']), ('2026-10-20', 'down'))  # an `on` the entry carries wins
        self.assertEqual(decline['reason'], 'decided by Kim on 2026-10-20 (declined a cut); it holds until 2026-11-17, '
                                            'so a person decides')
        self.assertIsNone(locks[key('Bid change:5')]['direction'])
        self.assertIsNone(locks[key('Bid change:6')]['direction'])  # a direction that can't be read holds every move
        self.assertEqual(locks[key('Bid change:5')]['reason'], 'decided by Kim on 2026-10-19 (declined this row); '
                                                               'it holds until 2026-11-16, so a person decides')
        self.assertEqual(locks[key('Bid change:7')]['reason'], 'decided by a person (declined this row); it holds until '
                                                               'further notice, so a person decides')
        self.assertEqual((locks[key('Bid change:7')]['by'], locks[key('Bid change:7')]['on']), (None, None))
        no_weeks, _ = plan_lanes.lock_table(dict(decisions=decisions))
        self.assertIsNone(no_weeks[key('Bid change:4')]['on'])  # no lock length: the date it was decided can't be known
        rows = [dict(keyword='cards', status='launched', approved_to_apply=True, review_on='2026-11-16', approved_by='Kim',
                     launched_on='2026-10-19'),
                dict(keyword='gold cards', status='proposed_not_applied')]
        locks, _ = plan_lanes.lock_table(dict(proposed_rank_experiments=dict(rows=rows)))
        self.assertEqual({k: locks['cards'][k] for k in ('what', 'by', 'on', 'direction')},
                         dict(what='experiment', by='Kim', on='2026-10-19', direction=None))
        self.assertEqual({k: locks['gold cards'][k] for k in ('what', 'by', 'on', 'direction')},
                         dict(what='experiment', by=None, on=None, direction=None))

    def test_an_approved_raise_does_not_hide_a_later_cut_from_a_person(self):
        """I3: Lee approved the raise on keyword 4. A week later it has 40 clicks and no order, and the planner wants
        a cut. The lock must not hide that call for 4 weeks, nor let the auto lane make it: it goes to a person."""
        decisions = [dict(id='Bid change:4', what='approve', by='Lee', until='2026-11-16', direction='up')]
        keywords = [k for k in KEYWORDS if k['KeywordId'] != '4'] + [keyword('4', 'cards', 'broad', BROAD, 0.37, 40, 0, 15)]
        out = self.plan(cfg=product(decisions=decisions), keywords=keywords, write_out=False)
        cut = one(out, 'Bid change', keyword_id='4')
        self.assertLess(cut['new'], cut['current'])
        self.assertEqual((cut['lane'], cut['lane_unlocked']), ('human', 'auto'))
        self.assertEqual((cut['locked_until'], cut['decided_by'], cut['decided_on'], cut['decision']),
                         ('2026-11-16', 'Lee', '2026-10-19', 'approve'))
        self.assertEqual(cut['lane_reason'], 'decided by Lee on 2026-10-19 (approved a raise, and this goes the other '
                                             'way); it holds until 2026-11-16, so a person decides')
        # the same lock leaves a further raise to the planner: it agrees with what Lee approved
        again = one(self.plan(cfg=product(decisions=decisions), write_out=False), 'Bid change', keyword_id='4')
        self.assertGreater(again['new'], again['current'])
        self.assertEqual((again['lane'], again['lane_unlocked']), ('auto', 'auto'))
        for field in ('locked_until', 'decided_by', 'decided_on', 'decision'):
            self.assertNotIn(field, again)

    def test_a_refused_auto_cut_stays_with_a_person_and_counts_for_the_gate(self):
        """I3: Lee refused the auto cut on keyword 3 in a shadow run. The next run still wants it: it is held for a
        person, and lane_unlocked keeps the planner's call (auto) visible for the shadow gate."""
        decisions = [dict(id='Bid change:3', what='decline', by='Lee', until='2026-11-16', direction='down')]
        out = self.plan(cfg=product(auto=dict(AUTO, enabled=False), decisions=decisions), write_out=False)
        cut = one(out, 'Bid change', keyword_id='3')
        self.assertEqual((cut['lane'], cut['lane_unlocked'], cut['decision'], cut['locked_until']),
                         ('human', 'auto', 'decline', '2026-11-16'))
        self.assertTrue(cut['lane_reason'].startswith('decided by Lee on 2026-10-19 (declined a cut)'))

    def test_every_row_records_its_lane_without_a_lock(self):
        out = self.plan(write_out=False)
        for x in out['changes']:
            self.assertEqual(x['lane_unlocked'], x['lane'], x['row_id'])
        unreadable = self.plan(cfg=product(decisions={'id': 'x'}), write_out=False)
        self.assertEqual({x['lane_unlocked'] for x in unreadable['changes']}, {'human'})

    def test_a_locked_bundle_records_the_lane_it_would_have_had(self):
        decisions = [dict(id='Pause keyword:2', what='decline', by='Kim', until='2026-11-16', direction='pause')]
        out = self.plan(cfg=product(decisions=decisions), write_out=False)
        bundle = ['New exact campaign:::blank cards', 'Pause keyword:2', 'Negative exact:101:201:blank cards',
                  'Negative exact:102:202:blank cards']
        for rid in bundle:
            x = next(c for c in out['changes'] if c['row_id'] == rid)
            self.assertEqual((x['lane'], x['lane_unlocked'], x['locked_until'], x['decided_by'], x['decision']),
                             ('human', 'auto', '2026-11-16', 'Kim', 'decline'), rid)
        # an approved pause holds the row whichever way the planner goes next
        approved = [dict(id='Pause keyword:2', what='approve', by='Kim', until='2026-11-16', direction='pause')]
        self.assertEqual(one(self.plan(cfg=product(decisions=approved), write_out=False), 'Pause keyword',
                             keyword_id='2')['lane'], 'human')

    # --- C3 (N1): a search created by an earlier apply is never proposed as a new creation ---------------------------
    def test_a_search_already_created_is_held_not_proposed_again(self):
        """`applied` wrote a create lock for the blank cards campaign; this run's data predates it, so it would propose the
        campaign again. The promotion and its bundle are held (read-only on the item, in held/), in both modes, matched by
        the search, not by the row id the lock happens to carry."""
        lock = dict(id='New exact campaign:999:888:blank cards', what='approve', by='Lee', on='2026-10-19',
                    until='2026-11-17', direction='other', kind='create', search='blank cards', created_on='2026-10-20')
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                out = self.plan(cfg=product(auto=dict(AUTO, enabled=enabled), decisions=[lock]))
                promo = one(out, 'New exact campaign', keyword='blank cards')
                self.assertEqual((promo['lane'], promo['locked_until'], promo['decided_by'], promo['decision']),
                                 ('human', '2026-11-17', 'Lee', 'approve'))
                self.assertTrue(promo['lane_reason'].startswith('already created on 2026-10-20 (approved by Lee)'),
                                promo['lane_reason'])
                self.assertIn('approving it does nothing', promo['lane_reason'])
                pause = one(out, 'Pause keyword', keyword_id='2')
                self.assertEqual((pause['lane'], pause['locked_until']), ('human', '2026-11-17'))
                held = read_rows(self.run_dir, 'held')
                self.assertIn(promo['row_id'], held['1_new_campaigns.json'])
                for folder in ('auto', 'review'):
                    path = os.path.join(self.run_dir, 'payloads', folder, 'rows.json')
                    ids = [rid for v in read_rows(self.run_dir, folder).values() for rid in v] if os.path.exists(path) else []
                    self.assertNotIn(promo['row_id'], ids)

    def test_a_create_lock_that_has_run_out_holds_nothing(self):
        lock = dict(id='New exact campaign:::blank cards', what='approve', on='2026-09-01', until='2026-09-29',
                    direction='other', kind='create', search='blank cards', created_on='2026-09-01')
        promo = one(self.plan(cfg=product(decisions=[lock]), write_out=False), 'New exact campaign', keyword='blank cards')
        self.assertEqual(promo['lane'], 'auto')
        self.assertNotIn('locked_until', promo)

    # --- B2 (I1): the dashboard's decisions reach the planner before every run, through <run>/reviews.json -----------
    def review(self, row_id, decision, by='Lee', at='2026-10-18T02:00:00.000Z', item_id='bids-2026-10-12', **kw):
        return dict(row_id=row_id, item_id=item_id, decision=decision, by=by, at=at, note=None, **kw)

    def test_load_lane_inputs_reads_the_saved_decisions(self):
        make_run(self.run_dir)
        self.assertIsNone(planner.load_lane_inputs(self.run_dir)['reviews'])
        saved = [self.review('Bid change:3', 'decline')]
        write(os.path.join(self.run_dir, 'reviews.json'), saved)
        self.assertEqual(planner.load_lane_inputs(self.run_dir)['reviews'], saved)
        with open(os.path.join(self.run_dir, 'reviews.json'), 'w', encoding='utf-8') as fh:
            fh.write('not json')
        self.assertNotIsInstance(planner.load_lane_inputs(self.run_dir)['reviews'], (list, type(None)))

    def test_a_saved_decline_locks_its_row_whichever_way_it_goes(self):
        """A decline nobody ran approvals for (decline-only weeks) still reaches the planner: until its SGT date plus
        lock_weeks, in every direction (the saved decision doesn't say which way the row went)."""
        reviews = [self.review('Bid change:3', 'decline'),                      # a cut
                   self.review('Bid change:1', 'decline', by='Kim', at='2026-10-17T18:00:00Z')]  # a raise; the 18th in SGT
        out = self.plan(write_out=False, extra={'reviews.json': reviews})
        for rid, by in (('Bid change:3', 'Lee'), ('Bid change:1', 'Kim')):
            x = next(c for c in out['changes'] if c['row_id'] == rid)
            self.assertEqual((x['lane'], x['lane_unlocked'], x['locked_until'], x['decided_by'], x['decided_on'], x['decision']),
                             ('human', 'auto', '2026-11-15', by, '2026-10-18', 'decline'), rid)
            self.assertIn('declined this row', x['lane_reason'])

    def test_only_the_latest_signed_decision_on_an_item_row_counts(self):
        reviews = [self.review('Bid change:3', 'decline'),
                   self.review('Bid change:3', 'approve', by='Kim', at='2026-10-18T03:00:00Z'),
                   self.review('Bid change:5', 'approve', by='Kim', at='2026-10-18T09:00:00Z'),
                   self.review('Bid change:5', 'decline', at='2026-10-18T08:00:00Z'),  # listed later, decided earlier
                   self.review('Bid change:1', 'decline', by='  '), self.review('Bid change:4', 'decline', by=None),
                   'not an entry', self.review('Bid change:1', 'maybe'),
                   # another item's decline still holds: the latest on (bids-2026-10-05, Pause target:301) is a decline
                   self.review('Pause target:301', 'decline', item_id='bids-2026-10-05'),
                   self.review('Pause target:301', 'approve', by='Kim', at='2026-10-18T05:00:00Z')]
        out = self.plan(write_out=False, extra={'reviews.json': reviews})
        locked = {x['row_id'] for x in out['changes'] if x.get('locked_until')}
        self.assertEqual(locked, {'Pause target:301'})

    def test_the_longer_of_a_saved_decline_and_a_product_file_lock_wins(self):
        decisions = [dict(id='Bid change:3', what='decline', by='Kim', on='2026-10-19', until='2026-11-30', direction='down')]
        out = self.plan(cfg=product(decisions=decisions), write_out=False,
                        extra={'reviews.json': [self.review('Bid change:3', 'decline')]})
        x = one(out, 'Bid change', keyword_id='3')
        self.assertEqual((x['locked_until'], x['decided_by']), ('2026-11-30', 'Kim'))
        short = [dict(id='Bid change:3', what='decline', by='Kim', on='2026-10-01', until='2026-10-29', direction='down')]
        out = self.plan(cfg=product(decisions=short), write_out=False,
                        extra={'reviews.json': [self.review('Bid change:3', 'decline')]})
        x = one(out, 'Bid change', keyword_id='3')
        # G2: Lee's saved decline holds longer, but Kim's still holds today, so his rank sets who may approve it
        self.assertEqual((x['locked_until'], x['decided_by'], x['decided_on']), ('2026-11-15', 'Kim', '2026-10-01'))
        self.assertIn('Kim declined it too, on 2026-10-01', x['lane_reason'])
        # once Kim's decline no longer holds, Lee's is the only one, and it names her
        ended = [dict(id='Bid change:3', what='decline', by='Kim', on='2026-09-01', until='2026-09-29', direction='down')]
        out = self.plan(cfg=product(decisions=ended), write_out=False,
                        extra={'reviews.json': [self.review('Bid change:3', 'decline')]})
        x = one(out, 'Bid change', keyword_id='3')
        self.assertEqual((x['locked_until'], x['decided_by']), ('2026-11-15', 'Lee'))

    def test_the_highest_ranked_saved_decline_names_the_lock(self):
        """G2 (N2): in the saved decisions, a later decline from a lower rank on the same item doesn't replace the earlier,
        higher one; on another week's item it holds longer but still names the higher decliner while that one holds. Only
        Kim's later approval on the item cancels the decline."""
        cases = (
            ([self.review('Bid change:3', 'decline', by='Kim', at='2026-10-18T02:00:00Z'),
              self.review('Bid change:3', 'decline', by='Lee', at='2026-10-18T03:00:00Z')], 'Kim', '2026-11-15'),
            ([self.review('Bid change:3', 'decline', by='Lee', at='2026-10-18T02:00:00Z'),
              self.review('Bid change:3', 'decline', by='Sam', at='2026-10-18T03:00:00Z')], 'Lee', '2026-11-15'),
            ([self.review('Bid change:3', 'decline', by='Sam', at='2026-10-18T02:00:00Z'),
              self.review('Bid change:3', 'decline', by='Lee', at='2026-10-18T03:00:00Z')], 'Lee', '2026-11-15'),
            # two weeks' items: Kim on the earlier, Lee on the later; hers holds longer, his rank still sets the bar
            ([self.review('Bid change:3', 'decline', by='Kim', at='2026-10-11T02:00:00Z', item_id='bids-2026-10-05'),
              self.review('Bid change:3', 'decline', by='Lee', at='2026-10-18T03:00:00Z')], 'Kim', '2026-11-15'),
            # Kim's approval after his own decline cancels it: Sam's decline after that names the lock
            ([self.review('Bid change:3', 'decline', by='Kim', at='2026-10-18T02:00:00Z'),
              self.review('Bid change:3', 'approve', by='Kim', at='2026-10-18T03:00:00Z'),
              self.review('Bid change:3', 'decline', by='Sam', at='2026-10-18T04:00:00Z')], 'Sam', '2026-11-15'))
        for n, (reviews, by, until) in enumerate(cases):
            with self.subTest(case=n):
                locks, problem = plan_lanes.lock_table({}, 4, reviews, '2026-10-19')
                self.assertIsNone(problem)
                lock = locks[lanes.lock_key('Bid change:3')]
                self.assertEqual((lock['what'], lock['by'], lock['until']), ('decline', by, until))

    def test_merging_declines_keeps_the_higher_decliner_only_for_the_moves_it_holds(self):
        """G2: a higher decline names the merged lock only while it holds (on the run's day) and only when it holds the
        same moves; a decline of a raise doesn't raise the bar on a declined cut."""
        today = datetime(2026, 10, 19).date()
        mel = dict(until='2026-11-15', what='decline', by='Lee', on='2026-10-18', direction='down', reason='m')
        for kim, by in ((dict(until='2026-10-29', what='decline', by='Kim', on='2026-10-01', direction='pause'), 'Kim'),
                          (dict(until='2026-10-29', what='decline', by='Kim', on='2026-10-01', direction=None), 'Kim'),
                          (dict(until='2026-10-29', what='decline', by='Kim', on='2026-10-01', direction='up'), 'Lee'),
                          (dict(until='2026-10-18', what='decline', by='Kim', on='2026-09-20', direction='down'), 'Lee'),
                          (dict(until='2026-10-29', what='approve', by='Kim', on='2026-10-01', direction='down'), 'Lee')):
            with self.subTest(kim=kim):
                before = copy.deepcopy((mel, kim))
                for a, b in ((mel, kim), (kim, mel)):
                    merged = plan_lanes.merge_locks(a, b, today)
                    self.assertEqual((merged['until'], merged['by'], merged['direction']), ('2026-11-15', by, 'down'))
                self.assertEqual((mel, kim), before)  # neither input is changed

    def test_decliners_rank_as_approvals_ranks_signers(self):
        for by in ('Kim', ' kim ', 'LEE', 'Lee', 'Sam', '', None, 'Kim Park'):
            with self.subTest(by=by):
                self.assertEqual(plan_lanes.decliner_rank(by), human_review.LEVELS.index(human_review.signer_level(by)))

    def test_a_by_hand_create_lock_says_to_add_the_keyword_to_its_campaign(self):
        """G3: a keyword of a Sponsored Brands video build whose campaign went out without it is held read-only, with
        words that say what to do."""
        lock = plan_lanes.decision_lock(dict(id='New SB video campaign:::zebra cards', what='approve', by='Lee',
                                             on='2026-10-19', until='2026-11-17', kind='create', search='zebra cards',
                                             created_on='2026-10-20', campaign='Cards - SB video 1', by_hand=True))
        self.assertEqual(lock['reason'], 'its campaign Cards - SB video 1 was created on 2026-10-20 without this keyword; '
                                         'add the keyword to it by hand. Nothing is proposed for it, and approving it does '
                                         'nothing')
        self.assertEqual(lock['kind'], 'create')

    def test_an_approval_in_the_saved_decisions_locks_nothing(self):
        """Approve locks come only from `applied`, once the row has gone out (B4)."""
        out = self.plan(write_out=False, extra={'reviews.json': [self.review('Bid change:1', 'approve')]})
        self.assertFalse([x for x in out['changes'] if x.get('locked_until')])

    def test_saved_decisions_that_cannot_be_read_send_everything_to_a_person(self):
        for saved in ({'error': 'x'}, 'garbage'):
            with self.subTest(saved=saved):
                out = self.plan(write_out=False, extra={'reviews.json': saved})
                self.assertEqual({x['lane'] for x in out['changes']}, {'human'})
                self.assertIn("the saved dashboard decisions (reviews.json) can't be read", out['changes'][0]['lane_reason'])

    def test_lock_table_reads_saved_declines(self):
        locks, problem = plan_lanes.lock_table({}, 4, [self.review('Bid change:3', 'decline', at='not a time')], '2026-10-19')
        self.assertIsNone(problem)
        lock = locks[lanes.lock_key('Bid change:3')]
        self.assertEqual((lock['until'], lock['what'], lock['by'], lock['on'], lock['direction']),
                         ('2026-11-16', 'decline', 'Lee', '2026-10-19', None))  # no readable time: the run's own day
        self.assertEqual(plan_lanes.lock_table({}, 4, None, '2026-10-19'), ({}, None))
        self.assertEqual(plan_lanes.lock_table({}, 4, {'x': 1}, '2026-10-19'), ({}, plan_lanes.UNREADABLE_REVIEWS))
        locks, _ = plan_lanes.lock_table({}, None, [self.review('Bid change:3', 'decline')], '2026-10-19')
        self.assertEqual(locks[lanes.lock_key('Bid change:3')]['until'], 'further notice')  # no lock_weeks: it holds

    # --- C5 (N4, concern b) and C6 (N5): the plan guard, and the dated saved decisions -------------------------------
    def bids_item(self, status='open'):
        item = human_review.validate([dict(id='bids-2026-10-12', kind='bid', title='x', reason='x', action='x', source='x',
                                           window='x', status='open', rows=[dict(row_id='Bid change:3', type='Bid change',
                                                                                 approval_required='owner')])])
        if status != 'open':
            item = human_review.transition(item, 'bids-2026-10-12', status, None, 'closed by the owner', '2026-10-13')
        return item

    def saved(self, entries, asin=ASIN, saved_at='2026-10-19T01:00:00Z'):
        """<run>/reviews.json as `dashboard.py reviews --save` writes it (C6)."""
        write(os.path.join(self.run_dir, 'reviews.json'), dict(asin=asin, saved_at=saved_at, entries=entries))

    def refused_main(self, cfg, *extra):
        with self.assertRaises(SystemExit) as cm:
            self.run_main(cfg, *extra)
        self.assertNotIn(cm.exception.code, (0, None))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'plan.json')))  # refused before planning
        return str(cm.exception.code)

    def test_main_needs_the_saved_decisions_while_the_product_holds_any_bids_item(self):
        """C5 (N4, the re-review's probe): the owner closed last week's item with `review --status resolved` and nobody ran
        approvals; its declines live only on the dashboard. Whatever the item's status, the plan needs them."""
        for status in ('open', 'resolved', 'dismissed'):
            with self.subTest(status=status):
                message = self.refused_main(product(human_review=self.bids_item(status)))
                self.assertIn('Save the dashboard decisions first: python scripts/dashboard.py reviews --asin B0TEST0001 '
                              '--save ', message)
                self.assertIn('bids-2026-10-12', message)
                self.assertIn('--no-reviews', message)
                # with the file saved, it plans, and the saved decline holds its row
                self.saved([self.review('Bid change:3', 'decline', item_id='bids-2026-10-12')])
                plan = self.run_main(product(human_review=self.bids_item(status)))
                self.assertEqual(one(plan, 'Bid change', keyword_id='3')['decided_by'], 'Lee')
                os.remove(os.path.join(self.run_dir, 'reviews.json'))
                os.remove(os.path.join(self.run_dir, 'plan.json'))
        self.run_main(product())  # a product that never had a bids item (a first run) needs no file

    def test_no_reviews_plans_with_every_change_for_a_person(self):
        """C5 (N5): while the dashboard can't be read, --no-reviews "<reason>" plans without the saved decisions, and then
        nothing goes out on its own: every change waits for a person, and says why. N-new-4: except a row the planner holds
        anyway (monitor), which stays held (test_no_reviews_keeps_the_rows_the_planner_holds_in_held)."""
        plan = self.run_main(product(human_review=self.bids_item()), '--no-reviews', 'the dashboard is down')
        judged = [x for x in plan['changes'] if x['lane'] != 'monitor']
        self.assertEqual({x['lane'] for x in judged}, {'human'})
        self.assertEqual({x['lane_reason'] for x in judged}, {"the dashboard decisions weren't read (the dashboard is down)"})
        self.assertEqual([x['row_id'] for x in plan['changes'] if x['lane'] == 'monitor'], ['Bid change:6'])
        self.assertEqual(read_payloads(self.run_dir, 'auto'), {})
        os.remove(os.path.join(self.run_dir, 'plan.json'))
        self.assertIn('needs the reason', self.refused_main(product(human_review=self.bids_item()), '--no-reviews', ' '))

    def test_no_reviews_keeps_the_rows_the_planner_holds_in_held(self):
        """N-new-4 (the re-review's P4): the degraded mode holds at least as much as a normal week. A row the planner holds
        anyway (monitor: a close call too small to bother anyone with) stays monitor, in held/, so a whole-run yes can't
        apply it; only the rows that would have been automatic or a person's call go to a person."""
        for shadow in (True, False):
            with self.subTest(shadow=shadow):
                cfg = product(auto=dict(AUTO, enabled=not shadow))
                normal = self.run_main(cfg)
                monitor = [x['row_id'] for x in normal['changes'] if x['lane'] == 'monitor']
                self.assertEqual(monitor, ['Bid change:6'])
                os.remove(os.path.join(self.run_dir, 'plan.json'))
                plan = self.run_main(cfg, '--no-reviews', 'the dashboard is down')
                self.assertEqual([x['row_id'] for x in plan['changes'] if x['lane'] == 'monitor'], monitor)
                kept = one(plan, 'Bid change', keyword_id='6')
                self.assertEqual(kept['lane_reason'], one(normal, 'Bid change', keyword_id='6')['lane_reason'])
                others = [x for x in plan['changes'] if x['lane'] != 'monitor']
                self.assertTrue(others)
                self.assertEqual({x['lane'] for x in others}, {'human'})
                self.assertEqual({x['lane_reason'] for x in others}, {"the dashboard decisions weren't read (the dashboard is down)"})
                counts = plan['summary'][0]['lanes']
                self.assertEqual((counts['auto'], counts['monitor'], counts['human']), (0, 1, len(others)))
                self.assertEqual(read_payloads(self.run_dir, 'auto'), {})
                self.assertEqual(read_rows(self.run_dir, 'held'), {'4_bids_01.json': ['Bid change:6']})
                held_rows = {rid for ids in read_rows(self.run_dir, 'review').values() for rid in ids}
                self.assertNotIn('Bid change:6', held_rows)
                os.remove(os.path.join(self.run_dir, 'plan.json'))

    def test_only_a_later_approval_by_kim_cancels_a_saved_decline(self):
        """Concern (b): Lee refused the cut on keyword 3; a later approval by anyone else (here a sweeper, below the
        row's level) leaves her refusal standing, as approvals reads it. Only Kim's later approval cancels it."""
        refused = self.review('Bid change:3', 'decline', at='2026-10-18T02:00:00Z')
        swept = self.review('Bid change:3', 'approve', by='Sam', at='2026-10-18T03:00:00Z')
        lee = self.review('Bid change:3', 'approve', by='Lee', at='2026-10-18T04:00:00Z')
        for later in ([swept], [swept, lee]):
            with self.subTest(later=[e['by'] for e in later]):
                x = one(self.plan(write_out=False, extra={'reviews.json': [refused] + later}), 'Bid change', keyword_id='3')
                self.assertEqual((x['lane'], x['decided_by'], x['decision']), ('human', 'Lee', 'decline'))
        kim = self.review('Bid change:3', 'approve', by=' kim ', at='2026-10-18T05:00:00Z')
        x = one(self.plan(write_out=False, extra={'reviews.json': [refused, swept, kim]}), 'Bid change', keyword_id='3')
        self.assertNotIn('locked_until', x)
        # a decline after Kim's approval holds again
        again = self.review('Bid change:3', 'decline', by='Sam', at='2026-10-18T06:00:00Z')
        x = one(self.plan(write_out=False, extra={'reviews.json': [refused, kim, again]}), 'Bid change', keyword_id='3')
        self.assertEqual(x['decided_by'], 'Sam')

    def test_the_saved_decisions_are_read_in_their_dated_shape(self):
        make_run(self.run_dir)
        entries = [self.review('Bid change:3', 'decline')]
        self.saved(entries)
        self.assertEqual(planner.load_lane_inputs(self.run_dir)['reviews'], entries)
        write(os.path.join(self.run_dir, 'reviews.json'), dict(asin=ASIN, saved_at='2026-10-19T01:00:00Z', entries='x'))
        self.assertNotIsInstance(planner.load_lane_inputs(self.run_dir)['reviews'], (list, type(None)))

    def test_main_refuses_saved_decisions_that_are_stale_or_for_another_product(self):
        """C6 (N5): an old file, or one copied from another run or product, can't stand in for today's decisions."""
        cfg = product(human_review=self.bids_item())
        entries = [self.review('Bid change:3', 'decline', item_id='bids-2026-10-12')]
        make_run(self.run_dir)
        write(os.path.join(self.run_dir, 'reviews.json'), entries)  # a bare list: when it was saved is unknown
        self.assertIn('save the dashboard decisions again', self.refused_main(cfg))
        self.saved(entries, asin='B0OTHER000')
        message = self.refused_main(cfg)
        self.assertIn('B0OTHER000', message)
        self.assertIn('save the dashboard decisions again', message)
        for stale in ('2026-10-17T15:59:00Z', 'not a time', None):  # 23:59 on the 17th in Singapore: 2 days before
            with self.subTest(saved_at=stale):
                self.saved(entries, saved_at=stale)
                self.assertIn('save the dashboard decisions again', self.refused_main(cfg))
        for fresh in ('2026-10-17T16:00:00Z', '2026-10-19T09:00:00Z'):  # the 18th in Singapore (a day before), and the day
            with self.subTest(saved_at=fresh):
                self.saved(entries, saved_at=fresh)
                self.assertEqual(one(self.run_main(cfg), 'Bid change', keyword_id='3')['decided_by'], 'Lee')
                os.remove(os.path.join(self.run_dir, 'plan.json'))

    # --- C8 (N6): a run folder that went out is never planned again --------------------------------------------------
    def folder_bytes(self):
        out = {}
        for root, _, names in os.walk(os.path.join(self.run_dir, 'payloads')):
            for name in names:
                with open(os.path.join(root, name), 'rb') as fh:
                    out[os.path.relpath(os.path.join(root, name), self.run_dir)] = fh.read()
        with open(os.path.join(self.run_dir, 'plan.json'), 'rb') as fh:
            out['plan.json'] = fh.read()
        return out

    def test_main_refuses_to_plan_a_run_folder_that_went_out(self):
        """N6 (the re-review's probe): auto/ (blank cards and its bundle) was applied and recorded; planning the same folder
        again would write the same campaign into auto/ once more. Any record, even an empty one, stops it."""
        self.run_main(product())
        for record in ({'New exact campaign:::blank cards': dict(date='2026-10-19', folder='auto')}, {}):
            with self.subTest(record=record):
                write(os.path.join(self.run_dir, 'payloads', 'applied_rows.json'), record)
                before = self.folder_bytes()
                with self.assertRaises(SystemExit) as cm:
                    self.run_main(product())
                self.assertIn('this run already went out (partly or whole); plan in a new run folder', str(cm.exception.code))
                self.assertEqual(self.folder_bytes(), before)

    def test_main_refuses_to_plan_a_run_folder_whose_approvals_were_handed_out(self):
        """approvals wrote payloads/approved/ (and it may be going out): a new plan.json would no longer be what those rows
        were approved from, so the folder is not planned again either."""
        self.run_main(product())
        approved = os.path.join(self.run_dir, 'payloads', 'approved')
        os.makedirs(approved)
        write(os.path.join(approved, 'rows.json'), {'4_bids_01.json': ['Bid change:1']})
        with self.assertRaises(SystemExit) as cm:
            self.run_main(product())
        self.assertIn("this run's approvals were handed out for an apply (payloads/approved/)", str(cm.exception.code))
        self.assertIn('plan in a new run folder', str(cm.exception.code))
        write(os.path.join(approved, 'rows.json'), {})  # a rows.json naming nothing hands nothing out
        self.run_main(product())

    # --- the Needs human "Bids" item, from a real plan (Task 6a, R1, R2, R4) ---------------------------------------
    def run_main(self, cfg, *extra, **run):
        make_run(self.run_dir, **run)
        data = os.path.join(self.tmp, 'data')
        os.makedirs(os.path.join(data, 'asins'), exist_ok=True)
        write(os.path.join(data, 'asins', f'{ASIN}.json'), cfg)
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--data', data, '--today', TODAY, *extra]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), without_mid():
            planner.main()
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            return json.load(fh)

    def test_main_stops_without_the_sponsored_brands_keywords_whatever_the_flags(self):
        """Decision 191 (Kim, 2026-11-05: "make sure we are optimizing both sponsored products and sponsored brands at the
        same time"): B0SAMP0007's Nov 5 run planned past its missing SB keyword read with --accept-unowned, and 847 SP bids
        went out with no SB bid. A product with a live SB campaign whose keywords weren't read now stops with exit 2 and
        nothing planned, flag or not; once the keywords are saved (even none) it plans."""
        sb = dict(campaignId='sb1', name=f'Cards - {ASIN} - Videos - Highest Converting Search Terms - Exact - 1',
                  state='ENABLED', budget=10, bidding=dict(bidOptimization=False))
        for flags in ((), ('--accept-unowned', 'SB keywords not saved this session'), ('--partial-inventory', 'time')):
            with self.subTest(flags=flags):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(os.path.join(self.run_dir, 'plan.json'))
                err = io.StringIO()
                with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(err):
                    self.run_main(product(), *flags, extra={'sb_campaigns_p1.json': dict(items=[sb]), 'sb_keywords_p1.json': None})
                self.assertEqual(cm.exception.code, 2)
                self.assertIn('sb_keywords', err.getvalue())
                self.assertIn('decision 191', err.getvalue())
                self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'plan.json')))
                self.assertTrue(os.path.exists(os.path.join(self.run_dir, 'need_sb_keywords.json')))
        saved = self.run_main(product(), extra={'sb_campaigns_p1.json': dict(items=[sb]), 'sb_keywords_p1.json': dict(items=[]),
                                                'sb_targets_p1.json': dict(items=[]), 'sb_themes_p1.json': dict(items=[])})
        self.assertNotIn('sb_keywords', saved['summary'][0]['coverage']['reads_missing'])

    def test_required_reads_are_only_the_listed_ones(self):
        import coverage
        cov = dict(reads_missing=['sb_keywords', 'live_sd_targets'])
        self.assertEqual(coverage.required_missing(cov, ['sb_keywords', 'live_ad_groups']), ['sb_keywords'])
        self.assertEqual(coverage.required_missing(cov, []), [])
        self.assertIsNone(coverage.required_stop([]))
        self.assertIn('need_sb_keywords.json', coverage.required_stop(['sb_keywords']))

    def test_main_judges_the_lanes_on_the_sgt_review_date(self):
        """A7 (M1): without --today, the lanes' today is the same SGT date the item id and the lock dates use, not the
        machine's date (a UTC machine on a Monday SGT morning is still on Sunday)."""
        make_run(self.run_dir, **HEAD_TERM)
        data = os.path.join(self.tmp, 'data')
        os.makedirs(os.path.join(data, 'asins'))
        # a one-word search's promotion is a person's call, so the run has rows for a person (and a Bids item)
        write(os.path.join(data, 'asins', f'{ASIN}.json'), product())
        argv = ['plan.py', '--asin', ASIN, '--run', self.run_dir, '--data', data]
        with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()), \
                unittest.mock.patch.object(planner, 'sgt_today', return_value=TODAY), \
                unittest.mock.patch.object(plan_lanes, 'assign', wraps=plan_lanes.assign) as spy, without_mid():
            planner.main()
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(spy.call_args.args[5], TODAY)
        with open(os.path.join(self.run_dir, 'plan.json'), encoding='utf-8') as fh:
            saved = json.load(fh)
        self.assertEqual([i['id'] for i in saved['human_review'] if i['kind'] == 'bid'], [f'bids-{TODAY}'])
        # A6: the plan records that date, so a publish can supersede older items even when the run had nothing to decide
        self.assertEqual(saved['summary'][0]['review_date'], TODAY)

    def test_main_writes_the_enabled_bids_item_into_plan_json(self):
        saved = self.run_main(product(), **HEAD_TERM)  # a one-word search's promotion: rows for a person
        self.assertIs(saved['summary'][0]['shadow'], False)
        bids = [i for i in saved['human_review'] if i['kind'] == 'bid']
        self.assertEqual([i['id'] for i in bids], ['bids-2026-10-19'])
        item = bids[0]
        self.assertEqual((item['status'], item['origin'], item['ai_review']['phase']), ('open', 'sweep', 'human_ready'))
        human = [x for x in saved['changes'] if x['lane'] == 'human']
        self.assertTrue(human)
        self.assertEqual({r['row_id'] for r in item['rows']}, {x['row_id'] for x in human})
        self.assertEqual(item['title'], f'{len(human)} bid change{"s" if len(human) != 1 else ""} to decide')
        self.assertIs(item['shadow'], False)
        self.assertEqual(item['locked_rows'], 0)
        self.assertEqual(human_review.validate(saved['human_review']), saved['human_review'])  # stored validated

    def test_main_writes_the_shadow_bids_item_with_every_row(self):
        saved = self.run_main(product(auto=dict(AUTO, enabled=False)))
        self.assertIs(saved['summary'][0]['shadow'], True)
        self.assertIn('auto', {x['lane'] for x in saved['changes']})
        item = next(i for i in saved['human_review'] if i['kind'] == 'bid')
        self.assertIs(item['shadow'], True)
        self.assertEqual(len(item['rows']), len(saved['changes']))
        self.assertEqual({r['lane'] for r in item['rows']}, {x['lane'] for x in saved['changes']})
        self.assertTrue(item['title'].endswith('to agree or refuse (shadow run)'))
        capped = [r for r in item['rows'] if 'new_capped' in r]
        self.assertTrue(capped)  # shadow auto raises past the cap carry the bid the auto lane would write

    def test_main_keeps_locked_rows_on_the_item(self):
        """A4: a row a person decided stays on the next run's item, marked with who decided it and when."""
        decisions = [dict(id='Bid change:5', what='decline', by='Lee', until='2026-11-16', direction='down')]
        saved = self.run_main(product(decisions=decisions))
        item = next(i for i in saved['human_review'] if i['kind'] == 'bid')
        row = next(r for r in item['rows'] if r['row_id'] == 'Bid change:5')
        self.assertEqual({k: row[k] for k in ('lane', 'lane_unlocked', 'locked_until', 'lock_by', 'lock_on', 'lock_decision')},
                         dict(lane='human', lane_unlocked='auto', locked_until='2026-11-16', lock_by='Lee',
                              lock_on='2026-10-19', lock_decision='decline'))
        self.assertEqual(item['locked_rows'], 1)
        self.assertIn('1 row is held by an earlier decision', item['reason'])

    def test_main_lists_every_waiting_row_even_when_all_are_locked(self):
        """A4: the item was dropped when every waiting row was locked, which also left an older item open (I4)."""
        first = self.run_main(product(), **HEAD_TERM)  # a one-word search's promotion: its bundle waits for a person
        waiting = [x['row_id'] for x in first['changes'] if x['lane'] == 'human']
        self.assertTrue(waiting)
        decisions = [dict(id=rid, what='decline', by='Kim', until='2026-11-16') for rid in waiting]
        saved = self.run_main(product(decisions=decisions), **HEAD_TERM)
        self.assertEqual([x['row_id'] for x in saved['changes'] if x['lane'] == 'human'], waiting)
        self.assertEqual({x['row_id'] for x in saved['changes'] if 'locked_until' in x}, set(waiting))
        item = next(i for i in saved['human_review'] if i['kind'] == 'bid')
        self.assertEqual({r['row_id'] for r in item['rows']}, set(waiting))
        self.assertEqual(item['locked_rows'], len(waiting))
        self.assertTrue(all(r['lock_by'] == 'Kim' for r in item['rows']))

    def test_a_real_plans_promotions_are_the_owners_whatever_they_spend(self):
        # until 2026-10-22 a promotion past Kim's $600 a month, with its bundle, was his; decision 99 made money a guide
        queries = QUERIES + [query('zebra cards', 4000, 1600, 160, 40, 8)]
        suggested = dict(SUGGESTED, **{'zebra cards': [0.55, 0.70, 0.90]})
        out = self.plan(cfg=product(auto=dict(AUTO, invest_guide_month=1)), queries=queries + [query('notecards', 2000, 800, 80, 30, 6)],
                        search_terms=HEAD_TERM['search_terms'], suggested=dict(suggested, notecards=[0.55, 0.70, 0.90]),
                        write_out=False)
        self.assertEqual(one(out, 'New exact campaign', keyword='blank cards')['lane'], 'auto')
        head = one(out, 'New exact campaign', keyword='notecards')
        self.assertEqual(head['lane'], 'human')   # a one-word search, not money, parks it
        self.assertIn('one-word search', head['lane_reason'])
        item = human_review.propose_bids(out, TODAY)
        self.assertEqual({r['approval_required'] for r in item['rows']}, {'owner'})
        self.assertEqual(one(out, 'New exact campaign', keyword='zebra cards')['lane'], 'auto')
        self.assertIs(out['summary'][0]['above_invest_guide'], True)

    # --- decision 99 (2026-10-22): no money level; the investment guide is information on the summary ----------------
    BIG = dict(queries=QUERIES + [query('kids cards', 60000, 8000, 400, 60, 4), query('party cards', 25000, 9500, 950, 60, 10),
                                  query('zebra cards', 4000, 1600, 160, 40, 8)],
               suggested=dict(SUGGESTED, **{'kids cards': [1.00, 1.20, 1.50], 'party cards': [0.60, 0.80, 1.00],
                                            'zebra cards': [0.55, 0.70, 0.90]}))

    def test_the_summary_carries_the_planned_invest_against_the_guide(self):
        out = self.plan(write_out=False, **self.BIG)
        s = out['summary'][0]
        auto = [p for p in by_type(out, 'New exact campaign') if p['lane'] == 'auto']
        self.assertTrue(auto)
        self.assertEqual(s['planned_invest_month'],
                         round(s['planned_invest_month_start'] + sum(p['modelled_spend_month'] for p in auto), 2))
        self.assertEqual((s['invest_guide_month'], s['above_invest_guide']), (2000, s['planned_invest_month'] > 2000))
        self.assertNotIn('kim_product_month', s)
        for x in out['changes']:
            self.assertNotIn('past_kim_level', x)
        # a guide under what is planned flags the summary and parks nothing
        low = self.plan(cfg=product(auto=dict(AUTO, invest_guide_month=1)), write_out=False, **self.BIG)
        self.assertIs(low['summary'][0]['above_invest_guide'], True)
        self.assertEqual([x['lane'] for x in low['changes']], [x['lane'] for x in out['changes']])

    def test_onboarding_promotions_are_judged_on_the_ladder_only(self):
        """C2: on an onboarding product every promotion was human for being onboarding, then (2026-10-22) the ones past
        Kim's $600 level were his. Since decision 99 nothing is parked for money: the ladder decides, and the bands are
        information (decision 100)."""
        cfg = product(registry=dict(bid_owner='AI', stage='ai', owner_since='2026-10-14'))
        out = self.plan(cfg=cfg, write_out=False, **self.BIG)
        promos = by_type(out, 'New exact campaign')
        self.assertEqual(len(promos), 4)
        self.assertFalse(any('onboarding' in p['lane_reason'] or 'a month of invest spend' in p['lane_reason'] for p in promos))
        self.assertEqual({p['lane'] for p in promos}, {'auto'})
        item = human_review.propose_bids(out, TODAY)
        self.assertEqual({r['approval_required'] for r in (item or {}).get('rows') or []} - {'owner'}, set())

    def test_a_real_plans_levels_in_shadow_mode(self):
        out = self.plan(cfg=product(auto=dict(AUTO, enabled=False)), write_out=False)
        item = human_review.propose_bids(out, TODAY)
        self.assertEqual(len(item['rows']), len(out['changes']))
        level = {r['row_id']: r['approval_required'] for r in item['rows']}
        promo = one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual(promo['lane'], 'auto')
        for rid in (promo['row_id'], 'Pause keyword:2', 'Negative exact:101:201:blank cards'):
            self.assertEqual(level[rid], 'owner', rid)  # a promotion inside Kim's level and its bundle (2026-10-22)
        self.assertEqual(level['Bid change:3'], 'owner')  # a cut on a Hold search, outside the rank searches
        self.assertEqual(level['Pause target:301'], 'owner')
        self.assertEqual(set(level.values()), {'owner'})
        self.assertEqual(item['approval_required'], 'owner')

    def test_bundles_group_a_promotion_with_its_pause_negatives_and_budget(self):
        out = self.plan(write_out=False)
        members, in_bundle = plan_lanes.bundles(out['changes'])
        (i, group), = members.items()
        self.assertEqual(out['changes'][i]['type'], 'New exact campaign')
        self.assertEqual(sorted(m['row_id'] for m in group),
                         ['Negative exact:101:201:blank cards', 'Negative exact:102:202:blank cards', 'Pause keyword:2'])
        self.assertEqual(len(in_bundle), 3)
        self.assertNotIn(i, in_bundle)

    # --- R7: a rank experiment's status is read as a word ------------------------------------------------------
    def test_lock_table_does_not_read_not_approved_as_approved(self):
        rows = [dict(keyword='alpha', status='approved', review_on='2026-11-16'),
                dict(keyword='bravo', status='Approved by Kim', review_on='2026-11-16'),
                dict(keyword='charlie', status='not_approved', review_on='2026-11-16'),
                dict(keyword='delta', status='unapproved', review_on='2026-11-16'),
                dict(keyword='echo', status='Not approved yet', review_on='2026-11-16'),
                dict(keyword='foxtrot', status='launched', approved_to_apply=True, review_on='2026-11-16'),
                dict(keyword='golf', status='approved', review_on=None)]  # approved but no review date: still pending
        locks, problem = plan_lanes.lock_table(dict(proposed_rank_experiments=dict(rows=rows)))
        self.assertIsNone(problem)
        until = {k: plan_lanes._until(v) for k, v in locks.items()}
        self.assertEqual(until, {'alpha': '2026-11-16', 'bravo': '2026-11-16', 'foxtrot': '2026-11-16',
                                 'charlie': 'further notice', 'delta': 'further notice', 'echo': 'further notice',
                                 'golf': 'further notice'})


# ----------------------------------------------------------------------------- the data stage (2026-10-22)
# A product in its first SQP weeks (docs/superpowers/specs/2026-10-21-keyword-selection-by-data-stage-design.md, sections
# 4.1 to 4.6): the gel pens' Oct 17 SQP cut down to four searches. The product has no launch block (it was onboarded before
# the design); roots ['pens'] stand in for a launch list, and the run may carry niche_keywords.json (the DataDive niche).
# (Until decision 99, 2026-10-22, Kim's monthly level was raised here to $1,500 so his running total, which counted the two
# head terms whatever their lane, left the brief's "room in the band"; no money level is left to raise.)
GEL_SKC = f'Cards - {ASIN} - Exact SKC - colored gel pens fine tip - TOS Rank'
IDS[GEL_SKC] = ('108', '208')
GEL_ROOTS = dict(roots=['pens'])
GEL_AUTO = dict(AUTO)
SUGGESTION = [0.30, 0.40, 0.50]
GEL_SUGGESTED = {t: SUGGESTION for t in ('gel pens for coloring', 'pen', 'school supplies', 'colored gel pens fine tip', 'pens colored')}
NICHE = dict(keywords=[dict(keyword='Gel Pens for Coloring'), dict(keyword='colored gel pens fine tip'), dict(keyword='pens colored')])
GEL_SEARCH_TERMS = [search_term('gel pens for coloring', STW, 30, 4, 15), search_term('pen', AUTO_CAMPAIGN, 8, 1, 4),
                    search_term('school supplies', AUTO_CAMPAIGN, 6, 1, 3), search_term('pen refills', STW, 20, 0, 8)]
GEL_KEYWORDS = [keyword('1', 'pen refills', 'exact', STW, 0.50, 20, 0, 8)]   # trails the market: a Trim cut
MATURE_EXTRA = [query('gel pen set', 3000, 1000, 100, 25, 2), query('glitter gel pens', 2500, 800, 80, 20, 2)]  # two more trusted Holds
FALLBACK_TERM = 'colored gel pens fine tip'


def gel_queries(days=21, head_days=14):
    """The four searches: `days` is the observed-day count of the two ordinary ones, `head_days` the two head terms'."""
    return [query('gel pens for coloring', 33884, 16422, 1622, 40, 5, observed_days=days),   # beats the market on 5 purchases: Invest
            query('pen', 136466, 31330, 5357, 12, 3, observed_days=head_days),                # beats the market, one word
            query('school supplies', 94201, 27858, 1894, 12, 2, observed_days=head_days),     # beats the market, not in the niche
            query('pen refills', 600, 300, 30, 30, 0, observed_days=days)]                     # trails the market on 30 clicks: Trim


def gel_product(**over):
    return product(relevance=GEL_ROOTS, auto=GEL_AUTO, **over)


class DataStageTest(unittest.TestCase):
    """The planner and the lanes read the data stage (data-stage design sections 4.1, 4.4, 4.6; built 2026-10-22): the
    stage on the summary and every row, early promotions to a person unless seen in two SQP weeks, the head-term flags,
    the search-term fallback's Prove first, volume from the next source down, the volatile-week hold, the Discovery cap
    lift and the launch-stage exit. The mature rules are untouched."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.run_dir = os.path.join(self.tmp, 'run')

    def plan(self, cfg=None, allow_volatile=False, write_out=False, **run):
        for name in ('soldscope_volume.json', 'niche_keywords.json'):   # a run folder planned again holds only what this call asks for
            if os.path.exists(os.path.join(self.run_dir, name)):
                os.remove(os.path.join(self.run_dir, name))
        make_run(self.run_dir, **run)
        cfg = cfg or gel_product()
        out = planner.build(ASIN, cfg, shared_config(), self.run_dir, 'weekly', TODAY, now_utc=NOW, allow_volatile=allow_volatile)
        if write_out:
            planner.write_outputs(self.run_dir, out, shared_config(), ASIN)
        return out

    def early(self, **over):
        """The gel pens in their third SQP week: 21 observed days, 4 trusted queries."""
        run = dict(queries=gel_queries(), search_terms=GEL_SEARCH_TERMS, keywords=GEL_KEYWORDS, suggested=GEL_SUGGESTED,
                   extra={'niche_keywords.json': NICHE})
        run.update(over)
        return self.plan(**run)

    def mature(self, **over):
        """The same searches with the full 84-day SQP window and 6 trusted queries."""
        run = dict(queries=gel_queries(84, 84) + MATURE_EXTRA, search_terms=GEL_SEARCH_TERMS, keywords=GEL_KEYWORDS,
                   suggested=GEL_SUGGESTED, extra={'niche_keywords.json': NICHE})
        run.update(over)
        return self.plan(**run)

    @staticmethod
    def term(out, t):
        return next(r for r in out['terms'] if r['term'] == t)

    def test_summary_carries_stage(self):
        early = self.early()
        self.assertEqual(early['summary'][0]['stage'],
                         dict(stage='early', sqp_queries=4, observed_days=21, trusted_queries=4, left_launch_this_run=False,
                              reason='early: 21 observed days, 4 trusted queries, 4 SQP queries with impressions'))
        self.assertEqual({r['stage'] for r in early['terms']}, {'early'})
        self.assertIsNone(early['summary'][0]['volatile_week'])
        mature = self.mature()
        self.assertEqual(mature['summary'][0]['stage']['stage'], 'mature')
        self.assertEqual(mature['summary'][0]['stage']['trusted_queries'], 6)
        self.assertEqual({r['stage'] for r in mature['terms']}, {'mature'})
        # the default fixture (84-day queries) is mature too, so every older test plans as it did
        self.assertEqual(self.plan(cfg=product())['summary'][0]['stage']['stage'], 'mature')

    def test_early_auto_needs_two_weeks_no_flag_no_volatile(self):
        out = self.early()
        gel = one(out, 'New exact campaign', keyword='gel pens for coloring')
        self.assertEqual(gel['role'], 'Invest')
        self.assertEqual(gel['lane'], 'auto', gel['lane_reason'])
        self.assertEqual(gel['sqp_observed_days'], 21)
        self.assertIsNone(gel['relevance_flag'])
        # the same search seen in one SQP week only: held until its second week (since 2026-10-22; a person decided before)
        week = one(self.early(queries=gel_queries(days=7)), 'New exact campaign', keyword='gel pens for coloring')
        self.assertEqual(week['lane'], 'monitor')
        self.assertTrue(week['lane_reason'].startswith('early SQP: '), week['lane_reason'])
        self.assertIn('seen in one SQP week only', week['lane_reason'])
        self.assertEqual(week['sqp_observed_days'], 7)
        pen = one(out, 'New exact campaign', keyword='pen')
        self.assertEqual((pen['role'], pen['lane']), ('Invest', 'human'))
        self.assertIn('one-word search', pen['lane_reason'])
        school = one(out, 'New exact campaign', keyword='school supplies')
        self.assertEqual((school['role'], school['lane']), ('Prove first', 'human'))
        self.assertIn("not in the product's niche list", school['lane_reason'])

    def test_head_flag_sends_to_person_at_every_stage(self):
        out = self.mature()
        self.assertEqual(out['summary'][0]['stage']['stage'], 'mature')
        pen = one(out, 'New exact campaign', keyword='pen')
        self.assertEqual(pen['lane'], 'human')
        self.assertIn('one-word search', pen['lane_reason'])
        school = one(out, 'New exact campaign', keyword='school supplies')
        self.assertEqual(school['lane'], 'human')
        self.assertIn("not in the product's niche list", school['lane_reason'])
        gel = one(out, 'New exact campaign', keyword='gel pens for coloring')
        self.assertEqual(gel['lane'], 'auto', gel['lane_reason'])

    def test_early_cuts_stay_auto(self):
        out = self.early()
        cut = one(out, 'Bid change', keyword='pen refills')
        self.assertEqual((cut['role'], cut['current'], cut['new']), ('Trim', 0.5, 0.1))
        self.assertEqual(cut['lane'], 'auto')
        self.assertEqual(cut['lane_reason'], 'cut from $0.50 to $0.10: a cut is never held back')

    def test_discovery_cap_lifts_at_two_orders(self):
        def discovery(orders, clicks):
            # a product converting at 6.6% on its ads (1000 clicks, 66 orders), profit $2.86: cap $0.19
            out = self.plan(cfg=product(profit_per_unit=2.86), search_terms=[search_term('gel pens', STW, 1000, 66, 500)],
                            keywords=[keyword('9', 'pens colored', 'phrase', BROAD, 1.15, clicks, orders, 6)])
            self.assertAlmostEqual(out['summary'][0]['asin_ad_cvr'], 0.066, places=4)
            self.assertEqual(out['summary'][0]['breakeven_click_avg'], 0.19)
            self.row = one(out, 'Bid change', keyword='pens colored')
            return next(p for p in out['keyword_plan'] if p['keyword_id'] == '9')
        lifted = discovery(2, 8)   # cvr (2 + 10 x 0.066) / 18 = 0.1478, keyword index 2.24: its own breakeven
        self.assertEqual(lifted['new_bid'], 0.42)
        self.assertIn('cap lifted: 2 orders at index 2.24', lifted['action'])
        # the lift is named on the Bid change row itself (final review, 2026-10-22): the preview, the dashboard and the log
        # read the row's why and cap_lifted, and write_outputs drops the keyword plan's action from plan.json
        self.assertEqual((self.row['current'], self.row['new'], self.row['cap_lifted']), (1.15, 0.42, '2 orders at index 2.24'))
        self.assertIn('Cap lifted here: 2 orders at index 2.24 against the product\'s ad conversion, so it bids its own '
                      'breakeven.', self.row['why'])
        one_order = discovery(1, 8)
        self.assertEqual(one_order['new_bid'], 0.19)
        self.assertIn('capped at the product average', one_order['action'])
        self.assertIsNone(self.row.get('cap_lifted'))
        self.assertNotIn('Cap lifted', self.row['why'])
        # 2 orders on 25 clicks: keyword index 1.15, over the 1.1 bar since decision 178 (under 1.25 until then; R7,
        # 2026-10-22: the brief's 20 clicks gives 1.34)
        self.assertIn('cap lifted: 2 orders at index 1.15', discovery(2, 25)['action'])
        # 2 orders on 30 clicks: keyword index 1.01, under the bar
        weak = discovery(2, 30)
        self.assertEqual(weak['new_bid'], 0.19)
        self.assertIn('capped at the product average', weak['action'])
        self.assertNotIn('cap lifted', weak['action'])

    def test_prove_bar_is_1_25(self):
        # the fixtures keep 1.25 (AUTO); the live bar is 1.1 since 2026-10-31 (Kim, decision 178: "anything above 1.1, we
        # will kind of rank"), fallback and the Discovery cap lift with it
        self.assertEqual(AUTO['prove_index'], 1.25)
        self.assertEqual((CONFIG['auto']['prove_index'], CONFIG['fallback']['prove_index'],
                          CONFIG['discovery']['cap_lift_index']), (1.1, 1.1, 1.1))
        self.assertEqual(lanes.ladder(2, 1.3, AUTO), 'Prove first')
        self.assertIsNone(lanes.ladder(2, 1.2, AUTO))
        sug = dict(SUGGESTED, **{'ink pens': [0.40, 0.50, 0.60]})
        # 2 purchases on 13 clicks against a 10% market: index 1.30 (mature, no flag: the ladder decides)
        out = self.plan(cfg=product(), queries=QUERIES + [query('ink pens', 5000, 1000, 100, 13, 2)], suggested=sug)
        t = self.term(out, 'ink pens')
        self.assertEqual((t['index'], t['sub_role'], t['index_status']), (1.3, 'Prove first', 'same_query_smoothed'))
        row = one(out, 'New exact campaign', keyword='ink pens')
        self.assertEqual(row['lane'], 'auto', row['lane_reason'])
        self.assertIn('enough proof for Prove first: 2 orders at index 1.30', row['lane_reason'])
        # 2 purchases on 15 clicks: index 1.20, the ladder returns nothing
        out = self.plan(cfg=product(), queries=QUERIES + [query('ink pens', 5000, 1000, 100, 15, 2)], suggested=sug)
        self.assertEqual(self.term(out, 'ink pens')['index'], 1.2)
        row = one(out, 'New exact campaign', keyword='ink pens')
        self.assertNotEqual(row['lane'], 'auto')
        self.assertIn('not enough proof yet for Prove first (needs 2+ orders at 1.25x the market)', row['lane_reason'])

    def test_fallback_prove_first_from_search_terms(self):
        out = self.early(search_terms=GEL_SEARCH_TERMS + [search_term(FALLBACK_TERM, AUTO_CAMPAIGN, 6, 3, 4)],
                         extra={'niche_keywords.json': NICHE, 'soldscope_volume.json': {FALLBACK_TERM: 250}})
        t = self.term(out, FALLBACK_TERM)
        self.assertEqual((t['role'], t['sub_role']), ('Rank', 'Prove first'))
        self.assertIsNone(t['index'])
        self.assertEqual(t['index_basis'], 'Search terms vs product market')
        self.assertEqual(t['index_status'], 'product_market_fallback')
        m = out['summary'][0]['asin_market_cvr']
        self.assertAlmostEqual(t['fallback_index'], round(((3 + 10 * m) / (6 + 10)) / m, 2), delta=0.011)
        self.assertGreaterEqual(t['fallback_index'], 1.25)
        # SoldScope's 250 a month, scaled to the product's 21-day window
        self.assertEqual((t['sqp_volume'], t['volume_basis'], t['observed_days'], t['sqp_observed_days']), (175, 'SoldScope', 21, None))
        self.assertEqual(t['stage'], 'early')
        self.assertIsNone(t['relevance_flag'])
        self.assertEqual([r['term'] for r in out['terms'] if r['fallback_index'] is not None], [FALLBACK_TERM])
        row = one(out, 'New exact campaign', keyword=FALLBACK_TERM)
        self.assertEqual(row['role'], 'Prove first')
        self.assertEqual(row['lane'], 'auto')   # decision 107: a small Prove-first test; a person approved it until 2026-10-23
        self.assertTrue(row['lane_reason'].startswith('Prove first on the search-term fallback (no SQP row yet)'), row['lane_reason'])
        self.assertIn('basis: Search terms vs product market; volume: SoldScope', row['evidence'])
        self.assertIn('175 searches in 21 days (SoldScope, scaled from a monthly figure)', row['evidence'])   # fix round 1, 2026-10-22
        self.assertNotIn('in 12 weeks', row['evidence'])
        self.assertIsNone(row['sqp_observed_days'])
        # the re-rank inverts the scaling: 175 searches in 21 days are 250 a month
        self.assertEqual(next(r for r in out['rerank'] if r['keyword'] == FALLBACK_TERM)['month_searches'], 250)

    def test_fallback_never_invest_and_needs_5_clicks(self):
        # two orders since 2026-10-31 (fallback.prove_orders, decision 174; three from 2026-10-25, decision 135)
        sts = GEL_SEARCH_TERMS + [search_term('fine point gel pen', AUTO_CAMPAIGN, 4, 3, 3), search_term('pens colored', AUTO_CAMPAIGN, 5, 3, 3),
                                  search_term('gel pens two orders', AUTO_CAMPAIGN, 5, 2, 3)]
        extra = {'niche_keywords.json': NICHE, 'soldscope_volume.json': {'fine point gel pen': 250, 'pens colored': 250,
                                                                         'gel pens two orders': 250}}
        out = self.early(search_terms=sts, extra=extra,
                         suggested=dict(GEL_SUGGESTED, **{'gel pens two orders': [0.40, 0.55, 0.70]}))
        few = self.term(out, 'fine point gel pen')   # 3 orders on 4 clicks: under the 5-click floor
        self.assertEqual((few['role'], few['fallback_index'], few['index_basis']), ('Test', None, 'Search terms'))
        two = self.term(out, 'pens colored')          # 3 orders on 5 clicks
        self.assertEqual((two['role'], two['sub_role']), ('Rank', 'Prove first'))
        two_orders = self.term(out, 'gel pens two orders')   # 2 orders on 5 clicks: the bar since decision 174
        self.assertEqual((two_orders['role'], two_orders['sub_role']), ('Rank', 'Prove first'))
        self.assertGreaterEqual(two['fallback_index'], 1.4)
        self.assertEqual(two['index_basis'], 'Search terms vs product market')
        self.assertIsNone(two['index'])
        for r in (few, two):
            self.assertNotEqual(r['index_basis'], 'SQP')
            self.assertEqual((r['sqp_volume'], r['volume_basis']), (175, 'SoldScope'))
        self.assertEqual(one(out, 'New exact campaign', keyword='pens colored')['lane'], 'auto')
        self.assertEqual([x for x in by_type(out, 'New exact campaign') if x['keyword'] == 'fine point gel pen'], [])
        # the fallback is early only: mature, both are Test
        mature = self.mature(search_terms=sts, extra=extra)
        for name in ('fine point gel pen', 'pens colored'):
            r = self.term(mature, name)
            self.assertEqual((r['role'], r['fallback_index'], r['stage']), ('Test', None, 'mature'), name)
            self.assertNotEqual(r['index_basis'], 'SQP')
            self.assertEqual((r['sqp_volume'], r['volume_basis']), (700, 'SoldScope'))
        self.assertEqual([x for x in by_type(mature, 'New exact campaign') if x['keyword'] in ('fine point gel pen', 'pens colored')], [])

    def test_fallback_prove_first_hands_over_to_same_query_index(self):
        # SQP now shows the query: 16 of our clicks and 1 purchase against a 15% market (R29)
        out = self.early(queries=gel_queries() + [query(FALLBACK_TERM, 800, 1000, 150, 16, 1, observed_days=21)],
                         search_terms=GEL_SEARCH_TERMS + [search_term(FALLBACK_TERM, AUTO_CAMPAIGN, 6, 3, 4)],
                         extra={'niche_keywords.json': NICHE, 'soldscope_volume.json': {FALLBACK_TERM: 250}})
        t = self.term(out, FALLBACK_TERM)
        self.assertIsNotNone(t['index'])
        self.assertEqual((t['index_status'], t['fallback_index'], t['index_basis'], t['role']),
                         ('same_query_smoothed', None, 'SQP', 'Trim'))
        self.assertEqual((t['sqp_volume'], t['volume_basis'], t['sqp_observed_days']), (800, 'SQP', 21))
        self.assertEqual([x for x in by_type(out, 'New exact campaign') if x['keyword'] == FALLBACK_TERM], [])

    def test_logged_fallback_prove_first_retained_when_mature(self):
        log = {FALLBACK_TERM: dict(since='2026-10-10', role='Prove first', index_then=None, imp_share_then=None, organic_then=0, rank_then=None)}
        out = self.mature(cfg=gel_product(invest_log=log),
                          search_terms=GEL_SEARCH_TERMS + [search_term(FALLBACK_TERM, GEL_SKC, 6, 3, 4)],
                          keywords=GEL_KEYWORDS + [keyword('9', FALLBACK_TERM, 'exact', GEL_SKC, 0.70, 6, 3, 4)],
                          more_campaigns=[campaign(GEL_SKC, budget=5, tos=30)])
        t = self.term(out, FALLBACK_TERM)
        self.assertEqual((t['role'], t['sub_role'], t['index'], t['fallback_index'], t['stage']), ('Rank', 'Prove first', None, None, 'mature'))
        self.assertIn('invest log', t['why'])
        self.assertEqual([x['type'] for x in out['changes'] if x['keyword'] == FALLBACK_TERM
                          and x['type'] in ('Bid change', 'New exact campaign', 'Reuse exact campaign', 'Pause keyword')], [])
        kw = next(p for p in out['keyword_plan'] if p['keyword_id'] == '9')
        self.assertTrue(kw['rank_investment_existing'])
        self.assertEqual(kw['new_bid'], 0.70)
        self.assertTrue(kw['action'].startswith('Keep pending visibility review'), kw['action'])
        self.assertIn(FALLBACK_TERM, [r['keyword'] for r in out['rerank_held']])
        self.assertEqual(out['summary'][0]['rank_reviews_deferred'], 1)

    def test_volume_of_feeds_the_150_gate(self):
        out = self.early(search_terms=GEL_SEARCH_TERMS + [search_term(FALLBACK_TERM, AUTO_CAMPAIGN, 6, 3, 4)],
                         extra={'niche_keywords.json': NICHE, 'soldscope_volume.json': {FALLBACK_TERM: 40}})
        t = self.term(out, FALLBACK_TERM)   # 40 a month is 28 in the 21-day window: under the 150-search gate
        self.assertEqual((t['role'], t['sqp_volume'], t['volume_basis'], t['observed_days'], t['fallback_index']),
                         ('Test', 28, 'SoldScope', 21, None))
        self.assertEqual([x for x in by_type(out, 'New exact campaign') if x['keyword'] == FALLBACK_TERM], [])
        # no source at all: volume 0, basis none, the full window
        plain = self.early(search_terms=GEL_SEARCH_TERMS + [search_term(FALLBACK_TERM, AUTO_CAMPAIGN, 6, 3, 4)])
        t = self.term(plain, FALLBACK_TERM)
        self.assertEqual((t['role'], t['sqp_volume'], t['volume_basis'], t['observed_days']), ('Test', 0, 'none', 84))
        # an SQP row with no volume of its own (QueryVolume 0, seen 7 days) takes SoldScope's figure scaled to the product's
        # 21-day window, and observed_days follows the volume source so monthly_searches inverts the scaling (R35, 2026-10-22);
        # the row's own count stays on sqp_observed_days, and its market still gives the search an index
        zero = self.early(queries=gel_queries() + [query(FALLBACK_TERM, 0, 100, 10, 0, 0, observed_days=7)],
                          search_terms=GEL_SEARCH_TERMS + [search_term(FALLBACK_TERM, AUTO_CAMPAIGN, 6, 3, 4)],
                          extra={'niche_keywords.json': NICHE, 'soldscope_volume.json': {FALLBACK_TERM: 250}})
        t = self.term(zero, FALLBACK_TERM)
        self.assertEqual((t['sqp_volume'], t['volume_basis'], t['observed_days'], t['sqp_observed_days']), (175, 'SoldScope', 21, 7))
        self.assertEqual((t['role'], t['index_status']), ('Rank', 'same_query_smoothed'))
        self.assertEqual(t['sqp_volume'] * 30 / t['observed_days'], 250)
        self.assertEqual(next(r for r in zero['rerank'] if r['keyword'] == FALLBACK_TERM)['month_searches'], 250)

    def test_fallback_term_live_keyword_raise_is_held(self):
        # R34 (fix round 1, 2026-10-22): the fallback term's exact SKC keyword is live at $2.00 and Amazon suggests 2.00/2.50/3.00,
        # so the Prove first re-price is a raise to $2.50, which the suggested-range rule would lane automatic with no index
        live = dict(search_terms=GEL_SEARCH_TERMS + [search_term(FALLBACK_TERM, GEL_SKC, 6, 3, 4)],
                    keywords=GEL_KEYWORDS + [keyword('9', FALLBACK_TERM, 'exact', GEL_SKC, 2.00, 6, 3, 4)],
                    more_campaigns=[campaign(GEL_SKC, budget=5, tos=30)],
                    suggested=dict(GEL_SUGGESTED, **{FALLBACK_TERM: [2.00, 2.50, 3.00]}),
                    extra={'niche_keywords.json': NICHE, 'soldscope_volume.json': {FALLBACK_TERM: 250}})
        out = self.early(**live)
        t = self.term(out, FALLBACK_TERM)
        self.assertEqual((t['index_status'], t['role'], t['sub_role']), ('product_market_fallback', 'Rank', 'Prove first'))
        row = one(out, 'Bid change', keyword=FALLBACK_TERM)
        self.assertEqual((row['role'], row['current'], row['new']), ('Prove first', 2.0, 2.5))   # the pricing stays; it is held
        self.assertEqual(row['lane'], 'monitor')   # decision 107: never a raise, never a person's call
        self.assertIn('its live keyword keeps its bid', row['lane_reason'])
        self.assertEqual([x for x in by_type(out, 'New exact campaign') if x['keyword'] == FALLBACK_TERM], [])   # the SKC owns it
        # the same keyword on a same-query-indexed search: the raise lanes as before (inside Amazon's suggested range)
        indexed = self.early(queries=gel_queries() + [query(FALLBACK_TERM, 800, 1000, 150, 16, 3, observed_days=21)], **live)
        t = self.term(indexed, FALLBACK_TERM)
        self.assertEqual((t['index_status'], t['role']), ('same_query_smoothed', 'Rank'))
        row = one(indexed, 'Bid change', keyword=FALLBACK_TERM)
        self.assertEqual((row['lane'], row['current'], row['new']), ('auto', 2.0, 2.5), row['lane_reason'])
        self.assertIn("inside Amazon's suggested range", row['lane_reason'])

    def test_terms_csv_carries_the_stage_columns(self):
        # MINOR 5 (fix round 1, 2026-10-22): the dry-run log reads terms.csv, so the stage fields follow the existing columns
        self.early(write_out=True, search_terms=GEL_SEARCH_TERMS + [search_term(FALLBACK_TERM, AUTO_CAMPAIGN, 6, 3, 4)],
                   extra={'niche_keywords.json': NICHE, 'soldscope_volume.json': {FALLBACK_TERM: 250}})
        with open(os.path.join(self.run_dir, 'terms.csv'), encoding='utf-8', newline='') as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(list(rows[0])[-6:], ['why', 'stage', 'volume_basis', 'relevance_flag', 'fallback_index', 'sqp_observed_days'])
        by_term = {r['term']: r for r in rows}
        fb = by_term[FALLBACK_TERM]
        self.assertEqual((fb['stage'], fb['volume_basis'], fb['relevance_flag'], fb['sqp_observed_days']), ('early', 'SoldScope', '', ''))
        self.assertGreaterEqual(float(fb['fallback_index']), 1.25)
        self.assertEqual((by_term['pen']['relevance_flag'], by_term['pen']['sqp_observed_days'], by_term['pen']['fallback_index']),
                         ('one token', '14', ''))

    def test_launch_stage_exits_with_its_message(self):
        cfg = product(launch=dict(date='2026-10-14', searches=[dict(search='gel pens for coloring', volume=9297)], roots=['pens']))
        make_run(self.run_dir, queries=gel_queries()[:3], search_terms=GEL_SEARCH_TERMS, keywords=GEL_KEYWORDS, suggested=GEL_SUGGESTED)
        with self.assertRaises(SystemExit) as cm:
            planner.build(ASIN, cfg, shared_config(), self.run_dir, 'weekly', TODAY, now_utc=NOW)
        msg = str(cm.exception)
        self.assertEqual(msg, f'{ASIN} is in the launch stage (3 SQP queries with impressions, under 10): build the launch list '
                              'with scripts/launch_list.py; the planner takes the product over at 10 queries')
        # a launch block whose date is None: early, not launch, and the run plans
        cfg = product(launch=dict(date=None, searches=[dict(search='gel pens for coloring', volume=9297)], roots=['pens']), auto=GEL_AUTO)
        out = planner.build(ASIN, cfg, shared_config(), self.run_dir, 'weekly', TODAY, now_utc=NOW)
        self.assertEqual(out['summary'][0]['stage']['stage'], 'early')

    def test_a_seasonal_product_is_not_stopped_at_the_launch_exit(self):
        # rulebook 10.1: a seasonal product is planned by its season block whatever the stage, so the same launch block
        # and 3 SQP queries plan when the product has a season block in a planning phase (final review, 2026-10-22). The
        # block is test_season.PLANNER_BLOCK with this fixture's own rank search; TODAY (2026-10-19) is in its rank build.
        block = dict(name='Test season 2026', holiday_key='thanksgiving', holiday='2026-11-26', wake='2026-10-04',
                     rank_build_start='2026-10-18', rank_build_end='2026-11-06', last_mile='2026-11-25', pause='2026-11-26',
                     review_by='2026-12-10', next_wake='2027-10-03', season_end='2026-11-28', rank_build=True,
                     rank_searches=['gel pens for coloring'], evergreen_searches=[], invest_cap=600, stop_loss_weeks=[2, 4])
        cfg = product(launch=dict(date='2026-10-14', searches=[dict(search='gel pens for coloring', volume=9297)], roots=['pens']),
                      season=block, auto=GEL_AUTO)
        make_run(self.run_dir, queries=gel_queries()[:3], search_terms=GEL_SEARCH_TERMS, keywords=GEL_KEYWORDS, suggested=GEL_SUGGESTED)
        out = planner.build(ASIN, cfg, shared_config(), self.run_dir, 'weekly', TODAY, now_utc=NOW)
        self.assertEqual(out['summary'][0]['stage']['stage'], 'launch')
        self.assertEqual(out['summary'][0]['stage']['sqp_queries'], 3)
        self.assertEqual(out['summary'][0]['season']['phase'], 'rank build')

    def test_relevance_flags_on_rows(self):
        out = self.early()
        self.assertEqual(self.term(out, 'pen')['relevance_flag'], 'one token')
        self.assertEqual(self.term(out, 'school supplies')['relevance_flag'], 'unlisted')
        self.assertIsNone(self.term(out, 'gel pens for coloring')['relevance_flag'])   # root "pens"
        # "pen" matches the root "pens" since the singular fold of 2026-10-22 (R41: a root matches its plural and singular),
        # so the cut carries no flag; before that day this read 'unlisted'
        self.assertIsNone(self.term(out, 'pen refills')['relevance_flag'])
        self.assertEqual(one(out, 'Bid change', keyword='pen refills')['lane'], 'auto')   # a cut is never held back
        # the launch list counts as a list, and so does the niche file alone
        listed = self.early(cfg=product(launch=dict(date=None, searches=[dict(search='school supplies', volume=100)]), auto=GEL_AUTO))
        self.assertIsNone(self.term(listed, 'school supplies')['relevance_flag'])
        self.assertEqual(self.term(listed, 'pen refills')['relevance_flag'], 'unlisted')
        niche_only = self.early(cfg=product(auto=GEL_AUTO))
        self.assertIsNone(self.term(niche_only, 'gel pens for coloring')['relevance_flag'])
        self.assertEqual(self.term(niche_only, 'school supplies')['relevance_flag'], 'unlisted')
        # a product with nothing to check against (no launch list, no niche file, no roots: every product onboarded before the
        # design) flags one-word searches only; "unlisted" needs a list (decided 2026-10-22, so the older fixtures plan as before)
        plain = self.early(cfg=product(auto=GEL_AUTO), extra={})
        self.assertEqual(self.term(plain, 'pen')['relevance_flag'], 'one token')
        self.assertIsNone(self.term(plain, 'school supplies')['relevance_flag'])
        self.assertEqual(one(plain, 'New exact campaign', keyword='pen')['relevance_flag'], 'one token')
        self.assertIn('flag: one token', one(plain, 'New exact campaign', keyword='pen')['evidence'])

    def test_volatile_week_holds_promotions(self):
        history = [dict(data_through='2026-10-10', our_clicks=214, our_purchases=3, queries=159)]
        # 462 of our clicks through 2026-10-17: the week added 248, more than the 214 of all earlier weeks
        queries = gel_queries(days=7) + [query('gel pens', 20000, 20000, 2000, 368, 37, observed_days=21)]
        run = dict(data_through='2026-10-17', queries=queries, search_terms=GEL_SEARCH_TERMS, keywords=GEL_KEYWORDS,
                   suggested=GEL_SUGGESTED, extra={'niche_keywords.json': NICHE})
        out = self.plan(cfg=gel_product(sqp_history=history), **run)
        s = out['summary'][0]
        self.assertEqual(s['volatile_week'], 'volatile SQP week: the SQP since 2026-10-10 (through 2026-10-17) added 248 of '
                                             'our clicks, more than the 214 of all earlier weeks')
        self.assertEqual(s['sqp_totals'], dict(our_clicks=462, our_purchases=47, queries=5))
        gel = one(out, 'New exact campaign', keyword='gel pens for coloring')
        self.assertEqual(gel['lane'], 'monitor')  # held for a steadier week, not escalated (2026-10-22)
        self.assertTrue(gel['lane_reason'].startswith('volatile SQP week'), gel['lane_reason'])
        self.assertIn('one-word search', one(out, 'New exact campaign', keyword='pen')['lane_reason'])  # the flag comes first
        self.assertEqual(one(out, 'Bid change', keyword='pen refills')['lane'], 'auto')                 # cuts are untouched
        lifted = self.plan(cfg=gel_product(sqp_history=history), allow_volatile=True, **run)
        s = lifted['summary'][0]
        self.assertIsNone(s['volatile_week'])
        self.assertTrue(s['volatile_week_overridden'].startswith('volatile SQP week'))
        gel = one(lifted, 'New exact campaign', keyword='gel pens for coloring')
        self.assertEqual(gel['lane'], 'monitor')
        self.assertTrue(gel['lane_reason'].startswith('early SQP: '), gel['lane_reason'])
        self.assertIn('seen in one SQP week only', gel['lane_reason'])
        # no history yet: no baseline, no hold
        self.assertIsNone(self.plan(**run)['summary'][0]['volatile_week'])

    def test_volatile_week_holds_only_in_early(self):
        # R38 (spec 4.6 "In early", 4.5 mature unchanged): the same SQP totals on a mature run are reported, not held
        history = [dict(data_through='2026-10-10', our_clicks=214, our_purchases=3, queries=159)]
        # 507 of our clicks through 2026-10-17: the week added 293, more than the 214 of all earlier weeks
        queries = gel_queries(84, 84) + MATURE_EXTRA + [query('gel pens', 20000, 20000, 2000, 368, 37)]
        run = dict(data_through='2026-10-17', queries=queries, search_terms=GEL_SEARCH_TERMS, keywords=GEL_KEYWORDS,
                   suggested=GEL_SUGGESTED, extra={'niche_keywords.json': NICHE})
        out = self.plan(cfg=gel_product(sqp_history=history), **run)
        s = out['summary'][0]
        self.assertEqual(s['stage']['stage'], 'mature')
        self.assertEqual(s['sqp_totals'], dict(our_clicks=507, our_purchases=51, queries=7))
        self.assertEqual(s['volatile_week'], 'volatile SQP week: the SQP since 2026-10-10 (through 2026-10-17) added 293 of '
                                             'our clicks, more than the 214 of all earlier weeks')   # still reported at every stage
        promos = {(x['type'], x['keyword']): x for x in out['changes'] if x['type'] in lanes.PROMOTION_TYPES}
        self.assertIn(('New exact campaign', 'gel pens for coloring'), promos)
        for key, x in promos.items():
            self.assertFalse(x['lane_reason'].startswith('volatile SQP week'), (key, x['lane_reason']))
        # each promotion takes the lane it had without the hold: the same run with no sqp_history (no baseline, no volatile text)
        plain = self.plan(cfg=gel_product(), **run)
        self.assertIsNone(plain['summary'][0]['volatile_week'])
        before = {(x['type'], x['keyword']): (x['lane'], x['lane_reason']) for x in plain['changes']
                  if x['type'] in lanes.PROMOTION_TYPES}
        self.assertEqual({k: (x['lane'], x['lane_reason']) for k, x in promos.items()}, before)

    def test_sqp_totals_file_written(self):
        out = self.early(write_out=True)
        with open(os.path.join(self.run_dir, 'sqp_totals.json'), encoding='utf-8') as fh:
            saved = json.load(fh)
        self.assertEqual(saved, dict(our_clicks=94, our_purchases=10, queries=4, data_through='2026-10-12'))
        self.assertEqual(out['summary'][0]['sqp_totals'], dict(our_clicks=94, our_purchases=10, queries=4))

    def test_launch_state_view(self):
        cfg = product(launch=dict(date='2026-10-14', searches=[]))
        nine = {f'gel pens {i}': query(f'gel pens {i}', 500, 100, 10, 5, 1, observed_days=7) for i in range(9)}
        view = planner.launch_state(cfg, nine, TODAY, shared_config())
        self.assertEqual(view, dict(active=True, sqp_queries=9, left_this_run=False,
                                    reason='launch: 7 observed days, 0 trusted queries, 9 SQP queries with impressions'))
        want = stage.data_stage(cfg, list(nine.values()), shared_config(), TODAY)
        self.assertEqual(view, dict(active=want['stage'] == 'launch', reason=want['reason'], sqp_queries=want['sqp_queries'],
                                    left_this_run=want['left_launch_this_run']))
        self.assertEqual(planner.launch_state(cfg, list(nine.values()), TODAY, shared_config()), view)  # a list of rows works too
        ten = dict(nine, **{'gel pens 9': query('gel pens 9', 500, 100, 10, 5, 1, observed_days=7)})
        left = planner.launch_state(dict(cfg, data_stage='launch'), ten, TODAY, shared_config())
        self.assertEqual((left['active'], left['sqp_queries'], left['left_this_run']), (False, 10, True))
        self.assertTrue(left['reason'].startswith('early: '))


if __name__ == '__main__':
    unittest.main()
