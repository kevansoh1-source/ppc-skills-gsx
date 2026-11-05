"""Decision 135 (Kim, 2026-10-25, the AI spend review): price every keyword and target, leaving none behind.

The live keyword and target reads join the plan; a keyword or target with no clicks of its own is never raised; the Test
floor stops at breakeven; audience copies are capped at breakeven; auto and Sponsored Display targets are priced; a copy
drops to a holding bid when its search's new exact campaign or SB video launches; Sponsored Brands bids on its own
conversion (older SB campaigns cut only, never under Amazon's $0.25); Prove first needs three orders (two since 2026-10-31, decision 174); a search SQP has
seen in fewer than 14 days waits at every stage; the Hold uplift test is off; onboarding opens the hours last.

Built on test_plan_lanes' synthetic run (make_run): profit $5.00 a unit, the product's ad conversion 13 orders on 88
clicks.
"""
import contextlib
import io
import json
import os
import sys
import unittest
import unittest.mock

import lanes
import plan as planner
import test_plan_lanes as T

AD_CVR = 13 / 88   # the fixture's search-term rows: the product's ad conversion
LIVE_BROAD = T.IDS[T.BROAD]
SD_CAMPAIGN = f'Cards - {T.ASIN} - Display Ad - Products Targeting'


def live_keyword(kid, text, match, campaign, bid, state='ENABLED'):
    cid, ag = T.IDS[campaign] if campaign in T.IDS else (campaign, 'g-' + campaign)
    row = dict(keywordId=kid, campaignId=cid, adGroupId=ag, keywordText=text, matchType=match.upper(), state=state)
    if bid is not None:
        row['bid'] = bid
    return row


def live_target(tid, expression, campaign, bid, expression_type='MANUAL'):
    cid, ag = T.IDS[campaign]
    return dict(targetId=tid, campaignId=cid, adGroupId=ag, expression=expression, expressionType=expression_type,
                state='ENABLED', bid=bid)


def sd_row(tid, campaign_id, bid, clicks, orders, name=SD_CAMPAIGN):
    return dict(AdType='SD', TargetId=tid, TargetText=f'B0SD{tid}', TargetType='product', CampaignId=campaign_id,
                AdGroupId='g' + campaign_id, CampaignName=name, Bid=f'${bid:.2f}', Clicks=str(clicks), Orders=str(orders),
                Spend='$1.00')


class PriceEverythingTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp
    plan = T.PlannerLanesTest.plan

    def build(self, live_keywords=(), live_targets=(), keywords=None, targets=None, shared=None, cfg=None, **extra_files):
        extra = {'live_keywords_p1.json': list(live_keywords), 'live_targets_p1.json': list(live_targets)}
        extra.update(extra_files)
        if targets is not None:
            extra['pt_p1.json'] = dict(data=targets)
        return self.plan(cfg=cfg, shared=shared, keywords=keywords, extra=extra)

    # --- the live keyword read -----------------------------------------------------------------------------------
    @staticmethod
    def never_raise():
        """The zero-click rule on (no_data_raise false), as it was until decision 168 (2026-10-29)."""
        s = T.shared_config()
        s['inventory']['no_data_raise'] = False
        return s

    def test_a_live_keyword_with_no_clicks_goes_to_its_price_since_decision_168(self):
        out = self.build(live_keywords=[live_keyword('10', 'nice cards', 'phrase', T.BROAD, 0.30)])
        up = T.one(out, 'Bid change', keyword_id='10')   # priced at its breakeven; the fixture's own auto block still caps the step
        self.assertEqual(next(p for p in out['keyword_plan'] if p['keyword_id'] == '10')['new_bid'], round(5 * AD_CVR, 2))
        self.assertGreater(up['new'], up['current'])
        self.assertIs(out['summary'][0]['inventory']['no_data_raise'], True)
        out = self.build(live_targets=[live_target('402', [dict(type='ASIN_SAME_AS', value='B0OTHER001')], T.PT, 0.20)])
        self.assertGreater(T.one(out, 'Target bid change', target_id='402')['new'], 0.20)

    def test_a_live_keyword_with_no_90_day_row_is_priced_and_never_raised(self):
        out = self.build(shared=self.never_raise(), live_keywords=[
            live_keyword('9', 'pretty cards', 'phrase', T.BROAD, 1.20),     # no row in Scale Insights, bid far above its price
            live_keyword('10', 'nice cards', 'phrase', T.BROAD, 0.30),     # no row, bid under its price: never raised
            live_keyword('11', 'old cards', 'phrase', T.BROAD, 1.20, state='PAUSED'),
            live_keyword('12', 'other cards', 'phrase', '999', 1.20),      # another product's campaign
            live_keyword('13', 'default cards', 'phrase', T.BROAD, None)])  # bids its ad group's default
        cut = T.one(out, 'Bid change', keyword_id='9')
        self.assertEqual((cut['current'], cut['new'], cut['role']), (1.2, round(5 * AD_CVR, 2), 'Discovery'))
        self.assertIn('No 90-day row in Scale Insights', cut['why'])
        self.assertEqual(cut['lane'], 'auto')
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') in ('10', '12', '13')], [])
        # the paused one is priced too, cut only, and stays paused (decision 155, 2026-10-27)
        old = T.one(out, 'Bid change', keyword_id='11')
        self.assertEqual((old['current'], old['new'], old['paused'], old['lane']), (1.2, round(5 * AD_CVR, 2), True, 'auto'))
        sent = [u for rows in T.read_payloads(self.run_dir, 'auto').values() for u in rows if u.get('keywordId') == '11']
        self.assertEqual([sorted(u) for u in sent], [['bid', 'keywordId', 'type']])
        nice = next(p for p in out['keyword_plan'] if p['keyword_id'] == '10')
        self.assertEqual(nice['new_bid'], 0.3)
        self.assertIn('never raised on this run', nice['action'])
        inventory = out['summary'][0]['inventory']
        # the 2 reported keywords of the broad campaign the read covered but doesn't hold are archived (not_live)
        self.assertEqual(inventory['keywords'], dict(added=2, paused_added=1, other_campaign=1, no_bid=1, not_live=2))
        self.assertTrue(inventory['live_keywords'])
        self.assertIs(inventory['no_data_raise'], False)

    def test_an_archived_keyword_is_never_priced(self):
        # 2026-10-26, B0SAMP0033: Amazon refused 2 bid rows on archived keywords priced from their 90-day rows. The live read
        # (enabled and paused) covers the broad campaign but doesn't hold keyword 4 ("cards"): it is archived
        out = self.build(live_keywords=[live_keyword('9', 'pretty cards', 'phrase', T.BROAD, 1.20)])
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == '4'], [])
        gone = next(p for p in out['keyword_plan'] if p['keyword_id'] == '4')
        self.assertIn('not in the live read', gone['action'])
        # a campaign the read holds nothing of is not judged: its keywords are priced as before
        self.assertTrue(any(x.get('keyword_id') == '1' for x in out['changes']) or
                        any(p['keyword_id'] == '1' and 'not in the live read' not in p['action'] for p in out['keyword_plan']))

    def test_a_reported_keyword_takes_its_live_bid_and_a_paused_one_is_cut_only(self):
        out = self.build(live_keywords=[live_keyword('3', 'gold cards', 'exact', T.STW, 0.65),
                                        live_keyword('5', 'greeting cards', 'phrase', T.BROAD, 1.50, state='PAUSED')])
        self.assertEqual(T.one(out, 'Bid change', keyword_id='3')['current'], 0.65)
        paused = T.one(out, 'Bid change', keyword_id='5')
        self.assertEqual((paused['current'], paused['paused']), (1.5, True))
        self.assertLess(paused['new'], 1.5)
        self.assertEqual(out['summary'][0]['inventory']['keywords'], dict(refreshed=2, not_live=4))

    def test_a_season_product_may_raise_a_keyword_with_no_clicks(self):
        # a seasonal wake raises on purpose: the rule is off for a product in season
        out = self.build(live_keywords=[live_keyword('10', 'nice cards', 'phrase', T.BROAD, 0.30)],
                         cfg=T.product(mode='harvest'))
        self.assertIs(out['summary'][0]['inventory']['no_data_raise'], True)

    # --- the Test floor and audience copies --------------------------------------------------------------------------
    def test_the_test_floor_stops_at_breakeven(self):
        # $2 a unit: the market price is $0.20 and breakeven at the product's ad conversion $0.30, under the $0.35 floor
        out = self.build(cfg=T.product(profit_per_unit=2.0))
        row = T.one(out, 'Bid change', keyword_id='8')   # gift cards: exact, no SQP row, no clicks
        self.assertEqual((row['role'], row['current'], row['new']), ('Test', 0.5, round(2.0 * AD_CVR, 2)))
        self.assertLess(row['new'], 0.35)

    def test_an_audience_copy_is_capped_at_breakeven_and_never_raised(self):
        keywords = T.KEYWORDS + [T.keyword('14', 'blank cards', 'broad', T.LOW, 1.00, 10, 0, 6)]
        out = self.build(keywords=keywords)
        row = T.one(out, 'Bid change', keyword_id='14')
        # breakeven on its own 10 clicks shrunk toward the product's ad conversion; the search has 6 orders, so the 63% cut
        # steps down 50% this run (the big-cut step) and the next run takes the rest
        self.assertEqual((row['role'], row['current'], row['new_proposed']), ('Audience cap', 1.0, round(5 * 10 * AD_CVR / 20, 2)))
        self.assertEqual((row['lane'], row['new']), ('auto', 0.5))
        # keyword 7 bids $0.20, under its breakeven: kept as it is
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == '7'], [])

    # --- targets: auto, live and Sponsored Display ---------------------------------------------------------------------
    def test_auto_targets_are_priced(self):
        auto = dict(T.target('310', 'close-match', 0.65, 30, 1, 20), TargetType='auto', CampaignName=T.AUTO_CAMPAIGN,
                    CampaignId=T.IDS[T.AUTO_CAMPAIGN][0], AdGroupId=T.IDS[T.AUTO_CAMPAIGN][1])
        out = self.build(targets=T.TARGETS + [auto])
        row = T.one(out, 'Target bid change', target_id='310')
        be = 5 * (1 + 10 * AD_CVR) / 40
        self.assertEqual((row['match'], row['role'], row['new']), ('auto', 'Trim', round(0.7 * be, 2)))
        off = T.shared_config()
        off['targets']['auto_targets'] = False
        out = self.build(targets=T.TARGETS + [auto], shared=off)
        self.assertEqual([x for x in out['changes'] if x.get('target_id') == '310'], [])

    def test_live_targets_with_no_row_are_priced_and_never_raised(self):
        out = self.build(shared=self.never_raise(), live_targets=[
            live_target('401', [dict(type='QUERY_BROAD_REL_MATCHES')], T.AUTO_CAMPAIGN, 1.11, 'AUTO'),
            live_target('402', [dict(type='ASIN_SAME_AS', value='B0OTHER001')], T.PT, 0.20)])
        row = T.one(out, 'Target bid change', target_id='401')
        self.assertEqual((row['keyword'], row['match'], row['current'], row['new']), ('loose-match', 'auto', 1.11, round(5 * AD_CVR, 2)))
        self.assertIn('No 90-day row in Scale Insights', row['why'])
        self.assertEqual([x for x in out['changes'] if x.get('target_id') == '402'], [])
        self.assertEqual(out['summary'][0]['inventory']['targets'], dict(added=2))
        self.assertEqual(out['summary'][0]['inventory']['targets_priced']['no clicks, kept'], 1)

    def test_sponsored_display_targets_are_priced_on_the_display_conversion(self):
        sd = [sd_row('501', '601', 1.10, 12, 0), sd_row('502', '602', 3.00, 40, 0), sd_row('503', '601', 0.80, 25, 0),
              sd_row('504', '603', 1.00, 5, 0)]
        campaigns = [dict(campaignId='601', name=SD_CAMPAIGN, state='enabled', costType='cpc'),
                     dict(campaignId='602', name=SD_CAMPAIGN, state='enabled', costType='vcpm')]
        out = self.build(**{'sd_targets_p1.json': dict(data=sd), 'sd_campaigns_p1.json': dict(items=campaigns)})
        sd_cvr = (0 + 10 * AD_CVR) / (12 + 25 + 10)   # the kept SD targets' pool: 37 clicks, no order
        row = T.one(out, 'Target bid change', target_id='501')
        be = 5 * (10 * sd_cvr) / 22
        self.assertEqual((row['ad_product'], row['role'], row['new']), ('SD', 'Test', round(max(0.1, be), 2)))
        self.assertIn("the product's display conversion", row['why'])
        pause = T.one(out, 'Pause target', target_id='503')
        self.assertEqual((pause['ad_product'], pause['how']), ('SD', 'MAP update sd_targets: state paused'))
        self.assertEqual([x for x in out['changes'] if x.get('target_id') in ('502', '504')], [])   # vCPM; campaign not read
        status = out['summary'][0]['inventory']['sponsored_display']
        self.assertIn('1 SD campaigns not read yet', status)
        self.assertIn('1 (vcpm campaign)', status)
        payloads = T.read_payloads(self.run_dir, 'auto')
        self.assertEqual(payloads['9b_sd_target_updates_01.json'],
                         [dict(type='sd_targets', targetId=503, state='paused'), dict(type='sd_targets', targetId=501, bid=row['new'])])
        self.assertNotIn('501', json.dumps(payloads.get('9_target_bids_01.json', [])))

    # --- consolidate before adding (fix 7) ---------------------------------------------------------------------------
    def test_a_copy_drops_to_a_holding_bid_when_its_search_gets_its_own_campaign(self):
        keywords = [dict(k, Bid=0.90) if k['KeywordId'] == '2' else k for k in T.KEYWORDS]
        out = self.build(keywords=keywords)
        T.one(out, 'New exact campaign', keyword='blank cards')
        pause = T.one(out, 'Pause keyword', keyword_id='2')
        hold = T.one(out, 'Bid change', keyword_id='2')
        self.assertEqual((hold['current'], hold['new'], hold['copy_hold']), (0.9, 0.5, True))   # 10% x $5 a unit
        self.assertEqual(hold['lane'], pause['lane'])
        self.assertNotIn('invested_search', hold)   # moving the search to its owner is never a step-down
        self.assertFalse(lanes.invested_cut(hold, frozenset({'blank cards'})))

    # --- Sponsored Brands on its own conversion (fix 9) ----------------------------------------------------------------
    def sb_files(self, keywords, perf=()):
        name = f'Cards - {T.ASIN} - Videos - Highest Converting Search Terms - Exact - '
        camps = [dict(campaignId='sb1', name=name + '1', state='ENABLED', budget=10),
                 dict(campaignId='sb2', name=f'Cards - {T.ASIN} - Video - Older', state='ENABLED', budget=10),
                 dict(campaignId='sb3', name=f'Cards - {T.ASIN} - Collection - Older', state='ENABLED', budget=10)]
        return {'sb_campaigns_p1.json': dict(items=camps), 'sb_keywords_p1.json': dict(items=keywords),
                'sb_kw_perf.json': dict(data=list(perf))}

    def sb_plan(self, keywords, perf=(), queries=None, asset='asset'):
        cfg = T.product(sb_video=dict(enabled=True, campaigns=['sb1'], video_asset_id=asset))
        files = self.sb_files(keywords, perf)
        files.update({'live_keywords_p1.json': [], 'live_targets_p1.json': []})
        return self.plan(cfg=cfg, extra=files, **({'queries': queries} if queries else {}))

    @staticmethod
    def sb_kw(kid, cid, text, match, bid):
        return dict(keywordId=kid, campaignId=cid, adGroupId='g' + cid, keywordText=text, matchType=match, state='ENABLED', bid=bid)

    def test_sb_bids_follow_the_sb_conversion_and_older_campaigns_are_cut_only(self):
        ratio, rank_ratio = T.CONFIG['sb_video']['sb_cvr_ratio'], T.CONFIG['sb_video']['sb_rank_ratio']
        out = self.sb_plan([self.sb_kw('k1', 'sb1', 'thank you cards', 'EXACT', 2.00),
                            self.sb_kw('k2', 'sb2', 'gold cards', 'EXACT', 1.50),
                            self.sb_kw('k3', 'sb3', 'cards', 'BROAD', 0.10),
                            self.sb_kw('k5', 'sb3', 'cards', 'BROAD', 1.40)],
                           perf=[dict(keywordId='k2', clicks=20, purchases=0, cost=12)])
        invest = T.one(out, 'SB bid change', keyword_id='k1')
        # the Sponsored Products invest bid (Amazon's suggested median $0.80, or breakeven if higher, never above the $1.00
        # high) x the rank ratio (a rank search keeps bidding to be visible); 8 orders, so the cut from $2.00 steps down 50%
        be = next(t for t in out['terms'] if t['term'] == 'thank you cards')['be_cpc']
        self.assertEqual(invest['new_proposed'], round(min(max(0.80, be), 1.00) * rank_ratio, 2))
        self.assertEqual(out['summary'][0]['sb_video']['sb_rank_ratio'], 1.0)
        self.assertEqual(invest['new'], 1.0)
        self.assertIn('a rank search keeps bidding to be visible in Sponsored Brands too', invest['why'])
        gold = T.one(out, 'SB bid change', keyword_id='k2')
        gold_cvr = next(t for t in out['terms'] if t['term'] == 'gold cards')['cvr_est'] * ratio
        self.assertEqual(gold['new'], round(max(0.25, 0.7 * 5 * (10 * gold_cvr) / 30), 2))
        self.assertIn("Older Sponsored Brands campaign (not the AI's video series): cut only.", gold['why'])
        broad = T.one(out, 'SB bid change', keyword_id='k5')
        self.assertEqual((broad['role'], broad['new']), ('Discovery', round(5 * AD_CVR * ratio, 2)))
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') == 'k3'], [])   # an older campaign is never raised
        self.assertEqual(out['summary'][0]['sb_video']['legacy_bid_cuts'], 2)

    def test_an_sb_copy_is_held_low_and_the_new_video_waits_with_a_held_promotion(self):
        copy = self.sb_kw('k4', 'sb2', 'blank cards', 'EXACT', 1.20)
        out = self.sb_plan([copy])
        video = T.one(out, 'New SB video campaign', keyword='blank cards')
        hold = T.one(out, 'SB bid change', keyword_id='k4')
        self.assertEqual((hold['new'], hold['copy_hold']), (0.5, True))
        # the copy is paused a run later, once the new video owns the search (2026-10-26)
        self.assertEqual(T.by_type(out, 'SB pause keyword'), [])
        promotion = T.one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual((video['lane'], hold['lane']), (promotion['lane'], promotion['lane']))
        # the search seen in one SQP week only: the promotion waits (decision 135, every stage) and its video waits with it
        queries = [q for q in T.QUERIES if q['Query'] != 'blank cards'] + [T.query('blank cards', 2000, 800, 80, 30, 6, observed_days=7)]
        out = self.sb_plan([copy], queries=queries)
        promotion = T.one(out, 'New exact campaign', keyword='blank cards')
        self.assertEqual(promotion['lane'], 'monitor')
        for row in (T.one(out, 'New SB video campaign', keyword='blank cards'), T.one(out, 'SB bid change', keyword_id='k4')):
            self.assertEqual(row['lane'], 'monitor')
            self.assertTrue(row['lane_reason'].startswith("waits with its search's exact campaign"), row['lane_reason'])

    def test_an_sb_copy_keeps_serving_while_its_new_video_is_held(self):
        # 2026-10-26, the prayer cards run: 15 older copies of 8 searches were paused while their videos were held for a
        # missing video asset, so the searches went dark in Sponsored Brands exact
        copy = self.sb_kw('k4', 'sb2', 'blank cards', 'EXACT', 1.20)
        out = self.sb_plan([copy], asset=None)
        video = T.one(out, 'New SB video campaign', keyword='blank cards')
        self.assertEqual(video['lane'], 'human')
        self.assertEqual(T.by_type(out, 'SB pause keyword'), [])
        hold = T.one(out, 'SB bid change', keyword_id='k4')
        self.assertEqual(hold['lane'], 'human')
        self.assertTrue(hold['lane_reason'].startswith("waits with its search's new SB video"), hold['lane_reason'])
        # once the AI's video owns the search (an enabled exact keyword in its own campaign), the copy is paused
        owned = self.sb_plan([copy, self.sb_kw('k1', 'sb1', 'blank cards', 'EXACT', 0.80)])
        self.assertEqual(T.one(owned, 'SB pause keyword', keyword_id='k4')['lane'], 'auto')

    # --- the inventory check and onboarding ----------------------------------------------------------------------------
    def test_main_stops_until_the_live_inventory_is_read(self):
        T.make_run(self.run_dir, inventory=False)
        argv = ['plan.py', '--asin', T.ASIN, '--run', self.run_dir]
        with unittest.mock.patch.object(sys, 'argv', argv), self.assertRaises(SystemExit) as cm, T.without_mid():
            planner.main()
        self.assertIn('need_live_inventory.json', str(cm.exception))
        with open(os.path.join(self.run_dir, 'need_live_inventory.json'), encoding='utf-8') as fh:
            need = json.load(fh)['need']
        self.assertEqual(set(need), {'live_keywords', 'live_targets', 'sd_targets', 'ad_campaigns'})
        self.assertEqual(need['live_keywords']['campaign_id_groups'], ['101,102,103,104,105,106'])
        with unittest.mock.patch.object(sys, 'argv', argv + ['--partial-inventory', ' ']), self.assertRaises(SystemExit) as cm, T.without_mid():
            planner.main()
        self.assertIn('needs the reason', str(cm.exception))
        T.make_run(self.run_dir)
        self.assertIsNone(planner.inventory_problem(self.run_dir, T.ASIN, T.CONFIG))

    def test_a_partial_inventory_is_recorded_on_the_summary(self):
        T.make_run(self.run_dir, inventory=False)
        out = planner.build(T.ASIN, T.product(), T.shared_config(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW,
                            partial_inventory='MAP down')
        inventory = out['summary'][0]['inventory']
        self.assertEqual((inventory['partial_reason'], inventory['live_keywords']), ('MAP down', False))

    def test_onboarding_opens_the_hours_last(self):
        T.make_run(self.run_dir)
        out = planner.build(T.ASIN, T.product(), T.shared_config(), self.run_dir, 'onboard', T.TODAY, now_utc=T.NOW)
        row = T.one(out, 'Scale Insights rules')
        self.assertIn('assigned last, once every MAP bid of this plan is written and read back', row['new'])
        self.assertIn('decision 135', row['why'])


class LiveConfigTest(unittest.TestCase):
    """The live rulebook values decision 135 set, and decision 174 changed."""

    def test_prove_first_needs_two_orders(self):
        # Kim, 2026-10-31 (decision 174): validated = 2+ orders, so the Prove-first bar is 2 again (3 from 2026-10-25,
        # decision 135). Invest and above-breakeven raises keep their 3-order bars
        a = T.CONFIG['auto']
        self.assertEqual((a['prove_orders'], T.CONFIG['fallback']['prove_orders']), (2, 2))
        self.assertEqual((a['prove_index'], a['invest_orders'], a['invest_index'], a['raise_orders'], a['raise_index']),
                         (1.1, 3, 1.1, 3, 1.4))   # prove_index 1.1 since decision 178 (1.25 before)
        self.assertEqual(lanes.ladder(2, 1.3, a), 'Prove first')
        self.assertEqual(lanes.ladder(2, 1.15, a), 'Prove first')
        self.assertIsNone(lanes.ladder(2, 1.05, a))
        self.assertIsNone(lanes.ladder(1, 2.0, a))
        self.assertEqual(lanes.ladder(3, 1.3, a), 'Invest')
        self.assertIsNone(lanes.ladder(3, 1.05, a))

    def test_hold_uplift_off_and_sb_on_its_own_conversion(self):
        self.assertIs(T.CONFIG['hold_uplift']['enabled'], False)
        sb = T.CONFIG['sb_video']
        self.assertEqual((sb['sb_cvr_ratio'], sb['sb_rank_ratio'], sb['min_bid']), (0.78, 1.0, 0.25))
        self.assertNotIn('sb_cpc_ratio', T.CONFIG['sb_video'])
        inv = T.CONFIG['inventory']
        self.assertEqual((inv['required'], inv['no_data_raise'], inv['copy_holding_bid_cvr']), (True, True, 0.1))
        self.assertTrue(T.CONFIG['targets']['auto_targets'] and T.CONFIG['targets']['sd'])


if __name__ == '__main__':
    unittest.main()
