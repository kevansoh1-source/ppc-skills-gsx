"""An invest search Amazon gives no suggested bid for (Kim, 2026-10-23, decision 106; bid_fallback.py): the run stops for
Amazon's suggestion only until Amazon was tried (bid_sources_tried.json); then the search is priced on SoldScope's estimate,
else an estimate (its own cost per click, or Amazon's median suggestion on the product's other searches, the higher), else
the no-suggestion bid, and every row says which. Runs on the lanes fixture (test_plan_lanes): 'blank cards' is the search
promoted to a new exact campaign, with 30 ad clicks at $18 (own cost per click $0.60)."""
import contextlib
import io
import json
import os
import unittest

import bid_fallback
import plan as planner
import test_business_roles as BR
import test_plan_lanes as T

TRIED = {'amazon': 'rate limited at 00:45 SGT after one retry 5 minutes later', 'soldscope': 'read for the missing searches'}
ONLY_THANK_YOU = {'thank you cards': T.SUGGESTED['thank you cards']}


def shared(**over):
    s = T.shared_config()
    s['bid_fallback'] = dict(own_cpc_min_clicks=10, peer_min_searches=3, **over)
    return s


class FillTest(unittest.TestCase):
    TERMS = {'own': dict(ad_cpc=0.6, ad_clicks=12), 'thin': dict(ad_cpc=2.0, ad_clicks=5), 'nothing': {}}
    PEERS = {'a': [0.4, 0.5, 0.7], 'b': [0.5, 0.7, 0.9], 'c': [0.6, 0.9, 1.2]}

    def test_soldscope_first_with_its_range(self):
        values, sources = bid_fallback.fill(['own'], {'own': [0.36, 0.53, 0.70]}, self.TERMS, self.PEERS, shared())
        self.assertEqual(values, {'own': [0.36, 0.53, 0.70]})
        self.assertEqual(sources['own'], ('soldscope', "SoldScope's estimate $0.53 ($0.36-$0.70)"))

    def test_the_higher_of_own_cost_per_click_and_the_peer_median(self):
        values, sources = bid_fallback.fill(['own'], {}, self.TERMS, self.PEERS, shared())
        self.assertEqual(values, {'own': [None, 0.7, None]})            # the peers' median 0.70 beats its own 0.60
        self.assertEqual(sources['own'][0], 'estimate')
        self.assertIn('the higher of its own cost per click $0.60 on 12 clicks and', sources['own'][1])
        self.assertIn("Amazon's median suggestion on 3 other searches, $0.70", sources['own'][1])

    def test_too_few_clicks_or_peers_count_for_nothing(self):
        two_peers = dict(list(self.PEERS.items())[:2])
        values, sources = bid_fallback.fill(['thin', 'nothing'], {}, self.TERMS, two_peers, shared())
        self.assertEqual(values, {})
        self.assertEqual(sources['thin'], ('none', '1.5x breakeven, with no SoldScope figure or estimate'))
        self.assertEqual(sources['nothing'][0], 'none')

    def test_a_zero_soldscope_figure_is_none(self):
        with self.subTest('loader'):
            run = os.path.join(self.tmp(), 'run')
            os.makedirs(run)
            with open(os.path.join(run, bid_fallback.SOLDSCOPE), 'w', encoding='utf-8') as fh:
                json.dump({'own': [0, 0, 0], 'Gold Cards': [0.3, 0.4, 0.5], '_note': 'job 1'}, fh)
            self.assertEqual(bid_fallback.load_soldscope(run, planner.load_suggested), {'gold cards': [0.3, 0.4, 0.5]})
        self.assertIsNone(bid_fallback.tried(run))

    def tmp(self):
        import tempfile
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        return d.name


class PlannerFallbackTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp

    def plan(self, extra=None, suggested=ONLY_THANK_YOU):
        T.make_run(self.run_dir, suggested=suggested, extra=extra)
        return planner.build(T.ASIN, T.product(), shared(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)

    def promo(self, out):
        return T.one(out, 'New exact campaign', keyword='blank cards')

    def be(self, out):
        return next(r['be_cpc'] for r in out['terms'] if r['term'] == 'blank cards')

    def test_harvest_retains_amazon_ranges_when_soldscope_exists(self):
        baseline = self.plan(extra={'bid_sources_tried.json': TRIED})['harvest']
        with_soldscope = self.plan(extra={'bid_sources_tried.json': TRIED,
                                         'soldscope_bids.json': {'blank cards': [2, 3, 4]}})['harvest']
        self.assertEqual(with_soldscope, baseline)
        self.assertEqual(baseline['bid_source'], 'amazon')

    def test_harvest_uses_real_soldscope_ranges_without_amazon(self):
        out = self.plan(suggested={}, extra={'bid_sources_tried.json': TRIED,
                                            'soldscope_bids.json': {'blank cards': [0.40, 0.60, 0.85]}})
        harvest = out['harvest']
        self.assertEqual(harvest['bid_source'], 'soldscope')
        self.assertEqual(harvest['median_of_medians'], 0.60)
        self.assertEqual(harvest['median_high'], 0.85)
        self.assertEqual(harvest['priced_searches'], 1)
        self.assertEqual(harvest['gate'], round(0.40 / T.product()['profit_per_unit'], 4))
        self.assertEqual(harvest['default_bid'], round(min(max(0.60, harvest['breakeven_click_avg']), 0.85), 2))

    def test_harvest_never_synthesizes_missing_ranges(self):
        for figures in ({}, {'blank cards': [None, 0.60, None]}, {'not an exact query': [0.4, 0.6, 0.8]},
                        {'blank cards': [0.8, 0.6, 0.4]}):
            with self.subTest(figures=figures):
                out = self.plan(suggested={}, extra={'bid_sources_tried.json': TRIED,
                                                    'soldscope_bids.json': figures})
                self.assertEqual(out['harvest'], {})

    def test_the_run_still_asks_for_amazon_first(self):
        printed = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(printed):
            self.plan()
        self.assertEqual(cm.exception.code, 2)
        with open(os.path.join(self.run_dir, 'need_suggested_bids.json'), encoding='utf-8') as fh:
            need = json.load(fh)
        self.assertEqual(need['searches'], ['blank cards'])
        self.assertIn('bid_sources_tried.json', need['how'])
        self.assertIn('soldscope_bids.json', need['how'])

    def test_soldscope_prices_a_search_amazon_has_none_for(self):
        out = self.plan(extra={'bid_sources_tried.json': TRIED, 'soldscope_bids.json': {'blank cards': [0.40, 0.60, 0.85]}})
        promo = self.promo(out)
        self.assertEqual(promo['bid_source'], 'soldscope')
        self.assertEqual((promo['sug_low'], promo['sug_median'], promo['sug_high']), (0.40, 0.60, 0.85))
        self.assertEqual(promo['new'], round(min(max(0.60, self.be(out)), 0.85), 2))
        self.assertIn("Amazon gave no suggested bid, so it is priced on SoldScope's estimate $0.60 ($0.40-$0.85).", promo['why'])
        fb = out['summary'][0]['bid_fallback']
        self.assertEqual(fb['tried'], TRIED)
        self.assertEqual(fb['searches'], {'blank cards': dict(source='soldscope', priced_on="SoldScope's estimate $0.60 ($0.40-$0.85)")})
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'need_suggested_bids.json')))

    def test_an_estimate_when_soldscope_has_none(self):
        out = self.plan(extra={'bid_sources_tried.json': TRIED, 'soldscope_bids.json': {'blank cards': [0, 0, 0]}})
        promo = self.promo(out)
        self.assertEqual(promo['bid_source'], 'estimate')
        self.assertEqual((promo['sug_low'], promo['sug_median'], promo['sug_high']), (None, 0.6, None))
        self.assertEqual(promo['new'], round(max(0.6, self.be(out)), 2))   # no high: the estimate, or breakeven if higher
        self.assertIn('its own cost per click $0.60 on 30 clicks', promo['why'])

    def test_with_nothing_at_all_it_bids_the_no_suggestion_price(self):
        thin = [T.search_term('blank cards', T.STW, 6, 4, 4), T.search_term('blank cards', T.AUTO_CAMPAIGN, 2, 1, 1)] + \
               [m for m in T.SEARCH_TERMS if m['SearchTerm'] != 'blank cards']
        T.make_run(self.run_dir, suggested=ONLY_THANK_YOU, search_terms=thin, extra={'bid_sources_tried.json': TRIED})
        out = planner.build(T.ASIN, T.product(), shared(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        promo = self.promo(out)
        self.assertEqual(promo['bid_source'], 'none')
        self.assertEqual(promo['new'], round(self.be(out) * 1.5, 2))
        self.assertIn('priced on 1.5x breakeven, with no SoldScope figure or estimate', promo['why'])

    def test_amazon_covered_runs_carry_no_fallback(self):
        out = self.plan(suggested=T.SUGGESTED)
        self.assertIsNone(out['summary'][0]['bid_fallback'])
        self.assertNotIn('bid_source', self.promo(out))


class SponsoredBrandsFallbackTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp

    def plan(self, owned=False, soldscope=None, thin=False, amazon=False):
        extra = {'sb_campaigns.json': {'items': [dict(campaignId='sb1', name=f'Cards - {T.ASIN} - Video - Exact - 1',
                                                     state='ENABLED', budget=10)]},
                 'sb_keywords_p1.json': {'items': [dict(keywordId='sbk1', campaignId='sb1', adGroupId='sbg1',
                                                       keywordText='blank cards', matchType='EXACT', state='ENABLED', bid=0.1)]}}
        if not amazon:
            extra['bid_sources_tried.json'] = TRIED
        if soldscope is not None:
            extra['soldscope_bids.json'] = {'blank cards': soldscope}
        search_terms = ([T.search_term('blank cards', T.STW, 6, 4, 4)] +
                        [r for r in T.SEARCH_TERMS if r['SearchTerm'] != 'blank cards']) if thin else None
        T.make_run(self.run_dir, suggested=T.SUGGESTED if amazon else ONLY_THANK_YOU,
                   search_terms=search_terms, extra=extra)
        cfg = T.product(sb_video=dict(enabled=True, campaigns=['sb1'] if owned else [],
                                      video_asset_id='test-asset'))
        return planner.build(T.ASIN, cfg, shared(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)

    def test_new_and_existing_sb_rank_bids_keep_soldscope_provenance(self):
        for owned in (False, True):
            with self.subTest(owned=owned):
                out = self.plan(owned=owned, soldscope=[0.4, 0.6, 0.85])
                row = T.one(out, 'SB bid change' if owned else 'New SB video campaign', keyword='blank cards')
                be = next(r['be_cpc'] for r in out['terms'] if r['term'] == 'blank cards')
                # x the rank ratio (1.0 since decision 135: a rank search keeps bidding to be visible; it was the 1.2 cost ratio)
                ratio = T.CONFIG['sb_video']['sb_rank_ratio']
                self.assertEqual(row.get('new_proposed', row['new']), round(min(max(0.6, be), 0.85) * ratio, 2))
                self.assertEqual(row['bid_source'], 'soldscope')
                self.assertIn("SoldScope's estimate $0.60 ($0.40-$0.85)", row['why'])
                self.assertIn("capped at that source's high", row['why'])
                self.assertNotIn("Amazon's suggested median", row['why'])
                if not owned:
                    self.assertEqual((row['sug_low'], row['sug_median'], row['sug_high']), (0.4, 0.6, 0.85))

    def test_sb_own_cpc_estimate_does_not_claim_a_high(self):
        row = T.one(self.plan(owned=True), 'SB bid change', keyword='blank cards')
        self.assertEqual(row['bid_source'], 'estimate')
        self.assertIn('its own cost per click $0.60 on 30 clicks', row['why'])
        self.assertIn('or breakeven if higher', row['why'])
        self.assertNotIn('the high', row['why'])
        self.assertNotIn("source's high", row['why'])

    def test_sb_no_estimate_explains_breakeven_multiplier(self):
        row = T.one(self.plan(thin=True), 'New SB video campaign', keyword='blank cards')
        self.assertEqual(row['bid_source'], 'none')
        self.assertIn('1.5x breakeven', row['why'])
        self.assertNotIn("Amazon's suggested median", row['why'])

    def test_sb_amazon_source_keeps_original_pricing_description(self):
        row = T.one(self.plan(amazon=True), 'New SB video campaign', keyword='blank cards')
        self.assertNotIn('bid_source', row)
        self.assertIn("Amazon's suggested median", row['why'])


class BusinessFallbackTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp
    plan = BR.BusinessRolesTest.plan
    shared = staticmethod(BR.shared)

    def test_a_business_search_with_amazon_tried_takes_the_no_suggestion_bid(self):
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            out = self.plan(suggested_b={'office cards': [0.50, 0.80, 1.20]}, extra={'bid_sources_tried.json': TRIED})
        self.assertNotIn('need_suggested_bids_business.json', printed.getvalue())
        row = T.one(out, 'Business invest', keyword='zebra cards')
        self.assertIsNone(row['sug_median'])
        self.assertEqual(out['summary'][0]['bid_fallback']['business_searches'], ['zebra cards'])


if __name__ == '__main__':
    unittest.main()
