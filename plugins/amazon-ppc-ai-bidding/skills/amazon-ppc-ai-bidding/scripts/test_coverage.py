"""Decision 155 (Kim, 2026-10-27, "Build 0 to 9, placement table included"): every campaign, keyword, target and
placement setting of an AI product has one owner in each run.

1. the placement policy: a non-rank campaign's top of search goes to 0% (the "TOS 900%" experiments too); a campaign
   whose boost can't come off this run prices its non-rank bids at price / (1 + boost); an audience copy moves to
   down-only bidding on its own.
2. older Sponsored Brands campaigns have Amazon's bid optimisation switched off.
3. Sponsored Brands product targets are priced; SB audience and B2B copies are capped.
4. dormant audience keywords are capped.
5. ad-group default bids are priced.
6. paused keywords, targets and campaigns are priced, cut only.
7. a multi-product campaign named in the product file is priced at the lowest profit, cut only.
0. the coverage ledger: every live entity has a status, and an unowned one stops the run.

Built on test_plan_lanes' synthetic run (make_run): profit $5.00 a unit, the product's ad conversion 13 orders on 88
clicks.
"""
import copy
import json
import os
import sys
import unittest
import unittest.mock

import coverage
import lanes
import placement_review
import plan as planner
import test_plan_lanes as T
import test_price_everything as P

AD_CVR = 13 / 88
EXPERIMENT = f'Cards - {T.ASIN} - Single Product Targeting - TOS 900% - B0SAMP0038'


def shared(**over):
    s = T.shared_config()
    s['targets']['skip_campaign_markers'] = []
    for k, v in over.items():
        s[k] = v
    return s


def campaigns(**tos):
    """The fixture's campaigns, with the top of search given by name (STW=100, ...) and the strategy as STW_strategy."""
    names = dict(STW=T.STW, AUTO=T.AUTO_CAMPAIGN, BROAD=T.BROAD, LOW=T.LOW, SKC=T.SKC, PT=T.PT)
    items = []
    for key, name in names.items():
        c = T.campaign(name, tos=tos.get(key, 50 if key == 'SKC' else 0))
        if tos.get(key + '_strategy'):
            c['optimizations']['bidSettings']['bidStrategy'] = tos[key + '_strategy']
        if tos.get(key + '_state'):
            c['state'] = tos[key + '_state']
        items.append(c)
    return items


def experiment_campaign(tos=900):
    return dict(campaignId='108', name=EXPERIMENT, state='ENABLED', budget=dict(budget=5),
                optimizations=dict(bidSettings=dict(bidStrategy='SALES_DOWN_ONLY', bidAdjustments=dict(
                    placementBidAdjustments=[dict(placement='PLACEMENT_TOP', percentage=tos),
                                             dict(placement='PLACEMENT_PRODUCT_PAGE', percentage=0)]))))


class Base(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp

    def plan(self, items=None, cfg=None, shared_cfg=None, extra=None, **run):
        files = {'live_keywords_p1.json': [], 'live_targets_p1.json': []}
        files.update(extra or {})
        if items is not None:
            files['campaigns.json'] = dict(items=items)
        T.make_run(self.run_dir, extra=files, **run)
        s = shared_cfg or shared()
        out = planner.build(T.ASIN, cfg or T.product(), s, self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        planner.write_outputs(self.run_dir, out, s, T.ASIN)
        return out

    def policy_rows(self, out):
        return [x for x in out['changes'] if x['type'] == 'Budget and top of search' and x.get('placement_policy')]


class PlacementPolicyTest(Base):
    def test_a_non_rank_campaign_goes_to_zero_on_its_own(self):
        out = self.plan(campaigns(STW=100))
        [row] = self.policy_rows(out)
        self.assertEqual((row['campaign_id'], row['tos_now'], row['tos'], row['budget'], row['budget_now']), ('101', 100, 0, 10, 10))
        self.assertEqual(row['lane'], 'auto')
        self.assertIn('decision 155', row['lane_reason'])
        # the rank campaign (the exact SKC of an invest search) keeps its +50%
        self.assertEqual([x for x in self.policy_rows(out) if x['campaign_id'] == '105'], [])
        payloads = T.read_payloads(self.run_dir, 'auto')
        updates = [u for name, rows in payloads.items() if 'campaign' in name for u in rows if u.get('campaignId') == '101']
        self.assertEqual(updates, [dict(type='sp_campaigns', campaignId='101', budget=dict(budget=10, budgetType='DAILY'),
                                        dynamicBidding=dict(strategy='LEGACY_FOR_SALES', placementBidding=[
                                            dict(placement='PLACEMENT_TOP', percentage=0)]))])
        # the bids of that campaign are priced as before: the boost comes off in the same run
        gold = T.one(out, 'Bid change', keyword_id='3')
        self.assertNotIn('boost_kept', gold)

    def test_a_campaign_that_keeps_its_boost_prices_for_it(self):
        base = T.one(self.plan(campaigns()), 'Bid change', keyword_id='3')['new']
        out = self.plan(campaigns(STW=100, STW_strategy='SALES_UP_AND_DOWN'))
        self.assertEqual(self.policy_rows(out), [])
        gold = T.one(out, 'Bid change', keyword_id='3')
        self.assertEqual((gold['priced_bid'], gold['new'], gold['boost_kept']), (base, round(base / 2, 2), 100))
        self.assertIn('+100% top-of-search boost', gold['why'])
        # the same run moves it to down only, so the next run takes the boost off
        self.assertEqual(T.one(out, 'Bidding strategy', campaign_id='101')['strategy'], 'SALES_DOWN_ONLY')

    def test_a_paused_campaign_is_set_too(self):
        out = self.plan(campaigns(BROAD=60, BROAD_state='PAUSED'))
        [row] = self.policy_rows(out)
        self.assertEqual((row['campaign_id'], row['campaign_state'], row['tos']), ('103', 'PAUSED', 0))
        self.assertIn('turning it back on starts at the policy', row['why'])

    def test_the_tos_900_experiment_ends_and_its_targets_are_priced(self):
        pt = dict(TargetId='309', TargetText='asin="B0SAMP0038"', TargetType='product', CampaignName=EXPERIMENT,
                  CampaignId='108', AdGroupId='208', AdType='SP', Bid=1.50, Clicks=12, Orders=1, Spend=14)
        out = self.plan(campaigns() + [experiment_campaign()], extra={'pt_p1.json': dict(data=T.TARGETS + [pt])})
        [row] = self.policy_rows(out)
        self.assertEqual((row['campaign_id'], row['tos_now'], row['tos']), ('108', 900, 0))
        self.assertIn('placement experiment: it ends here', row['why'])
        self.assertEqual(row['other_placements'], [dict(placement='PLACEMENT_PRODUCT_PAGE', percentage=0)])
        target = T.one(out, 'Target bid change', target_id='309')
        self.assertLess(target['new'], 1.50)
        self.assertNotIn('boost_kept', target)

    def test_an_experiment_with_audience_adjustments_keeps_its_boost_and_its_target_bids_around_both(self):
        exp = experiment_campaign()
        exp['optimizations']['bidSettings']['bidAdjustments']['audienceBidAdjustments'] = [dict(audienceId='1', percentage=20)]
        pt = dict(TargetId='309', TargetText='asin="B0SAMP0038"', TargetType='product', CampaignName=EXPERIMENT,
                  CampaignId='108', AdGroupId='208', AdType='SP', Bid=1.50, Clicks=12, Orders=1, Spend=14)
        out = self.plan(campaigns() + [exp], extra={'pt_p1.json': dict(data=T.TARGETS + [pt])})
        self.assertEqual(self.policy_rows(out), [])
        target = T.one(out, 'Target bid change', target_id='309')
        # +900% top of search kept, and the +20% audience boost priced around too (decision 156): price / (10 x 1.2)
        self.assertEqual(target['boost_kept'], 1100)
        self.assertEqual(target['new'], max(0.02, round(target['priced_bid'] / 12, 2)))
        self.assertIn('+900% top-of-search and +20% audience boosts', target['why'])

    def test_the_overnight_test_copies_are_left_alone(self):
        on80 = T.campaign(T.BROAD, tos=40)
        on80['name'] = 'ON80 | ' + T.BROAD
        items = [c for c in campaigns() if c['campaignId'] != '103'] + [on80]
        out = self.plan(items)
        self.assertEqual(self.policy_rows(out), [])

    def test_policy_off_plans_none(self):
        s = shared()
        s['placement']['policy'] = dict(s['placement']['policy'], enabled=False)
        self.assertEqual(self.policy_rows(self.plan(campaigns(STW=100), shared_cfg=s)), [])


class SponsoredBrandsTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp
    plan = T.PlannerLanesTest.plan
    sb_kw = staticmethod(P.PriceEverythingTest.sb_kw)

    def sb_plan(self, keywords=(), targets=None, camps_extra=(), perf=(), shared_cfg=None):
        files = P.PriceEverythingTest.sb_files(self, list(keywords), perf)
        files['sb_campaigns_p1.json']['items'] += list(camps_extra)
        if targets is not None:
            files['sb_targets_p1.json'] = dict(items=targets)
        files.update({'live_keywords_p1.json': [], 'live_targets_p1.json': []})
        cfg = T.product(sb_video=dict(enabled=True, campaigns=['sb1'], video_asset_id='asset'))
        return self.plan(cfg=cfg, shared=shared_cfg, extra=files)

    def test_an_audience_copy_is_capped_never_raised(self):
        amc = dict(campaignId='sb4', name=f'Cards - {T.ASIN} - Video - AMC - Low Bids', state='ENABLED', budget=5)
        out = self.sb_plan([self.sb_kw('k6', 'sb4', 'cards', 'BROAD', 1.40), self.sb_kw('k7', 'sb4', 'cards gift', 'BROAD', 0.25)],
                           camps_extra=[amc])
        row = T.one(out, 'SB bid change', keyword_id='k6')
        ratio = T.CONFIG['sb_video']['sb_cvr_ratio']
        self.assertEqual((row['role'], row['new'], row['lane']), ('Audience cap', round(max(0.25, 5 * AD_CVR * ratio), 2), 'auto'))
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == 'k7'], [])
        self.assertEqual(T.by_type(out, 'SB pause keyword'), [])

    def test_a_paused_campaign_is_cut_only_and_stays_paused(self):
        old = dict(campaignId='sb5', name=f'Cards - {T.ASIN} - Video - Paused', state='PAUSED', budget=5)
        out = self.sb_plan([self.sb_kw('k8', 'sb5', 'cards', 'BROAD', 1.40)], camps_extra=[old])
        row = T.one(out, 'SB bid change', keyword_id='k8')
        self.assertTrue(row['paused'])
        self.assertLess(row['new'], 1.40)
        sent = [u for rows in T.read_payloads(self.run_dir, 'auto').values() for u in rows if u.get('keywordId') == 'k8']
        self.assertNotIn('state', sent[0])

    def test_targets_are_priced_cut_only(self):
        targets = [dict(targetId='t1', campaignId='sb2', adGroupId='gsb2', state='ENABLED', bid=1.50,
                        resolvedExpressions=[dict(type='asinSameAs', value='B0SAMP0036')]),
                   dict(targetId='t2', campaignId='sb2', adGroupId='gsb2', state='ENABLED', bid=0.25)]
        out = self.sb_plan(targets=targets, perf=[dict(keywordId='t1', clicks=10, purchases=0, cost=9)])
        row = T.one(out, 'SB bid change', target_id='t1')
        self.assertEqual((row['role'], row['keyword'], row['lane']), ('Target cap', 'B0SAMP0036', 'auto'))
        self.assertLess(row['new'], 1.50)
        self.assertEqual([x for x in out['changes'] if x.get('target_id') == 't2'], [])
        sent = [u for rows in T.read_payloads(self.run_dir, 'auto').values() for u in rows if u.get('type') == 'sb_targets']
        self.assertEqual(sent, [dict(type='sb_targets', targetId='t1', adGroupId='gsb2', campaignId='sb2', bid=row['new'])])

    def test_targets_not_read_asks_for_them(self):
        self.sb_plan([self.sb_kw('k2', 'sb2', 'gold cards', 'EXACT', 1.50)])
        with open(os.path.join(self.run_dir, 'need_sb_keywords.json')) as fh:
            need = json.load(fh)
        self.assertIs(need['keywords_read'], True)
        self.assertIs(need['targets_read'], False)
        self.assertIn('sb_targets', need['how'])

    def test_bid_optimisation_is_switched_off_with_positive_placements_to_zero(self):
        opt = dict(campaignId='sb6', name=f'Cards - {T.ASIN} - Video - Optimised', state='ENABLED', budget=5,
                   bidding=dict(bidOptimization=True, bidAdjustmentsByPlacement=[dict(placement='TOP_OF_SEARCH', percentage=60),
                                                                                 dict(placement='DETAIL_PAGE', percentage=-20)]))
        out = self.sb_plan(camps_extra=[opt])
        [row] = T.by_type(out, 'SB bid optimisation')
        self.assertEqual((row['campaign_id'], row['lane']), ('sb6', 'auto'))
        sent = [u for rows in T.read_payloads(self.run_dir, 'auto').values() for u in rows if u.get('type') == 'sb_campaigns']
        self.assertEqual(sent, [dict(type='sb_campaigns', campaignId='sb6', bidding=dict(bidOptimization=False, bidAdjustmentsByPlacement=[
            dict(placement='TOP_OF_SEARCH', percentage=0), dict(placement='DETAIL_PAGE', percentage=-20)]))])
        self.assertEqual(out['summary'][0]['sb_video']['bid_optimisation_off'], 1)


class DormantAndDefaultsTest(Base):
    def test_a_dormant_audience_keyword_is_capped(self):
        recent = [dict(keywordId='77', keyword='blank cards bulk', matchType='BROAD', campaignName=T.LOW, cost=4, clk=3, ord=0, bid=1.10),
                  dict(keywordId='78', keyword='cheap cards', matchType='BROAD', campaignName=T.LOW, cost=1, clk=1, ord=0, bid=0.20)]
        out = self.plan(campaigns(), extra={'recent_kw.json': dict(data=recent)})
        row = T.one(out, 'Bid change', keyword_id='77')
        self.assertEqual((row['role'], row['new'], row['lane']), ('Audience cap', round(5 * AD_CVR, 2), 'auto'))
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == '78'], [])

    def ad_groups(self, *rows):
        return {'live_ad_groups_p1.json': dict(items=[dict(adGroupId=ag, campaignId=cid, state=st, defaultBid=bid)
                                                       for ag, cid, st, bid in rows])}

    def test_ad_group_defaults_are_priced_cut_only(self):
        out = self.plan(campaigns(), extra=self.ad_groups(('203', '103', 'ENABLED', 1.50), ('204', '104', 'PAUSED', 1.20),
                                                          ('202', '102', 'ENABLED', 0.30), ('205', '105', 'ENABLED', 2.00)))
        rows = {x['ad_group_id']: x for x in T.by_type(out, 'Ad group default bid')}
        price = round(5 * AD_CVR, 2)
        self.assertEqual((rows['203']['current'], rows['203']['new'], rows['203']['lane']), (1.5, price, 'auto'))
        self.assertTrue(rows['204']['paused'])
        self.assertNotIn('202', rows)    # under its price: never raised
        self.assertNotIn('205', rows)    # the exact SKC of an invest search: a rank campaign
        sent = [u for rows_ in T.read_payloads(self.run_dir, 'auto').values() for u in rows_ if u.get('type') == 'sp_ad_groups']
        self.assertIn(dict(type='sp_ad_groups', adGroupId='203', defaultBid=price), sent)
        self.assertEqual(out['summary'][0]['inventory']['ad_group_defaults']['cut'], 2)

    def test_the_harvest_ad_group_keeps_its_own_bid(self):
        cfg = T.product()
        cfg['harvest'] = dict(cfg.get('harvest') or {}, ad_group_id='203')
        out = self.plan(campaigns(), cfg=cfg, extra=self.ad_groups(('203', '103', 'ENABLED', 1.50)))
        self.assertEqual(T.by_type(out, 'Ad group default bid'), [])

    def test_not_read_is_said(self):
        out = self.plan(campaigns(), extra={'live_ad_groups_p1.json': None})
        self.assertEqual(out['summary'][0]['inventory']['ad_group_defaults'], {'not read': 1})


class SharedCampaignTest(Base):
    """The dormant shared-campaign pricing (decision 155), switched off by decision 156 (multi-ASIN campaigns are left out
    on purpose): these tests switch it back on to keep the code working for a later change of mind."""
    SHARED = 'Cards - Cross-Selling - Bookmarks and Cards'

    def plan(self, items=None, cfg=None, shared_cfg=None, extra=None, **run):
        s = shared_cfg or shared()
        s['inventory'] = dict(s['inventory'], shared_campaigns=True)
        return super().plan(items, cfg=cfg, shared_cfg=s, extra=extra, **run)

    def setup_files(self, low=2.5, tos=40):
        shared_c = T.campaign(T.BROAD, tos=tos)
        shared_c.update(campaignId='901', name=self.SHARED)
        live = [P.live_keyword('91', 'pretty cards', 'phrase', '901', 1.20)]
        live[0]['adGroupId'] = '991'
        cfg = T.product()
        cfg['shared_campaigns'] = [dict(campaign_id='901', products=[T.ASIN, 'B0OTHERAI1'], profit_per_unit_min=low)]
        return cfg, {'shared_campaigns.json': dict(items=[shared_c]), 'live_keywords_p1.json': live}

    def test_a_shared_campaign_is_priced_at_the_lowest_profit_cut_only(self):
        cfg, extra = self.setup_files()
        out = self.plan(campaigns(), cfg=cfg, extra=extra)
        row = T.one(out, 'Bid change', keyword_id='91')
        self.assertEqual((row['new'], row['shared_campaign']), (round(round(5 * AD_CVR, 2) * 0.5, 2), True))
        self.assertIn('lowest profit', row['why'])
        policy = [x for x in self.policy_rows(out) if x['campaign_id'] == '901']
        self.assertEqual(len(policy), 1)
        self.assertEqual(out['summary'][0]['inventory']['shared_campaigns']['read'], 1)

    def test_no_lowest_profit_leaves_it_alone(self):
        cfg, extra = self.setup_files(low=None)
        out = self.plan(campaigns(), cfg=cfg, extra=extra)
        self.assertEqual([x for x in out['changes'] if x.get('campaign_id') == '901'], [])
        self.assertEqual(out['summary'][0]['inventory']['shared_campaigns']['no_profit'], ['901'])


class LedgerTest(Base):
    def test_every_live_entity_has_an_owner(self):
        live = [P.live_keyword('9', 'pretty cards', 'phrase', T.BROAD, 1.20),
                P.live_keyword('11', 'old cards', 'phrase', T.BROAD, 1.20, state='PAUSED'),
                P.live_keyword('13', 'default cards', 'phrase', T.BROAD, None)]
        out = self.plan(campaigns(STW=100), extra={'live_keywords_p1.json': live, 'live_ad_groups_p1.json': None})
        cov = out['summary'][0]['coverage']
        self.assertEqual(cov['unowned'], 0)
        kinds = cov['by_kind']
        self.assertEqual(kinds['sp_keyword'], {'changed': 2, 'ad_group_default': 1})
        self.assertEqual(kinds['sp_campaign']['policy'], 1)
        self.assertIn('live_ad_groups', cov['reads_missing'])
        self.assertIsNone(coverage.stop_reason(cov))
        self.assertIn('live_ad_groups', coverage.stop_reason(cov, stop_on_missing=True))   # decision 156

    def test_a_target_a_skip_marker_leaves_out_is_unowned_and_stops_the_run(self):
        s = T.shared_config()   # targets.skip_campaign_markers ['TOS'], as before decision 155
        pt = dict(TargetId='309', TargetText='asin="B0SAMP0038"', TargetType='product', CampaignName=EXPERIMENT,
                  CampaignId='108', AdGroupId='208', AdType='SP', Bid=1.50, Clicks=12, Orders=1, Spend=14)
        live_t = [dict(targetId='309', campaignId='108', adGroupId='208', expression=[], expressionType='MANUAL', state='ENABLED', bid=1.5)]
        out = self.plan(campaigns() + [experiment_campaign()], shared_cfg=s,
                        extra={'pt_p1.json': dict(data=T.TARGETS + [pt]), 'live_targets_p1.json': live_t})
        cov = out['summary'][0]['coverage']
        self.assertEqual([(e['kind'], e['id']) for e in cov['unowned_rows']], [('sp_target', '309')])
        self.assertIn('--accept-unowned', coverage.stop_reason(cov))

    def test_sb_bid_optimisation_left_on_is_unowned(self):
        s = shared()
        s['sb_video'] = dict(s['sb_video'], bid_optimisation_off=False)
        opt = dict(campaignId='sb6', name=f'Cards - {T.ASIN} - Video - Optimised', state='ENABLED', budget=5,
                   bidding=dict(bidOptimization=True))
        out = self.plan(campaigns(), shared_cfg=s, extra={'sb_campaigns_p1.json': dict(items=[opt]), 'sb_keywords_p1.json': dict(items=[])})
        cov = out['summary'][0]['coverage']
        self.assertEqual([(e['kind'], e['id']) for e in cov['unowned_rows']], [('sb_campaign', 'sb6')])


class AudienceDownOnlyTest(unittest.TestCase):
    kind = staticmethod(lambda name: 'audience' if 'AMC' in (name or '') else 'consumer')

    def test_an_audience_copy_moves_on_its_own(self):
        amc = dict(campaignId='555', name=f'Cards - {T.ASIN} - AMC - Low Bids 0.25', state='ENABLED', budget=dict(budget=5),
                   optimizations=dict(bidSettings=dict(bidStrategy='SALES_UP_AND_DOWN', bidAdjustments=dict(
                       placementBidAdjustments=[dict(placement='TOP_OF_SEARCH', percentage=0)]))))
        snap = dict(live_asins={'555': [T.ASIN]})
        ctx = lanes.Ctx(auto=dict(T.AUTO), profit_per_unit=5.0, stale=None, onboarding=False, locks={}, today=T.TODAY,
                        band_left_month=0, raises_left=3)
        plc = dict(down_only=dict(enabled=True, audience_auto=True))
        [row] = placement_review.strategy_rows([amc], T.ASIN, plc, self.kind, snap)
        self.assertTrue(row['audience'] and row['audience_auto'])
        self.assertEqual(lanes.classify(row, None, ctx)[0], 'auto')
        self.assertIn('moves on its own too', row['why'])
        # not shown to advertise this product alone: still a person's
        [row] = placement_review.strategy_rows([amc], T.ASIN, plc, self.kind, dict(live_asins={'555': [T.ASIN, 'B0OTHER001']}))
        self.assertEqual(lanes.classify(row, None, ctx)[0], 'human')
        # audience_auto off: as before
        [row] = placement_review.strategy_rows([amc], T.ASIN, dict(down_only=dict(enabled=True)), self.kind, snap)
        self.assertEqual(lanes.classify(row, None, ctx)[0], 'human')


if __name__ == '__main__':
    unittest.main()
