"""Bids priced on each search's own SQP conversion (Kim, 2026-10-29, decision 162), and no count cap on raises
(decision 164). config.json pricing.search_conversion 'sqp': an exact keyword bids its search's SQP price (all our clicks on
the listing for that search, ads and organic, shrunk toward the search's market by the 10-click prior), its own ad record no
longer pulling it toward its ad conversion; a search SQP has no clicks of ours for falls back to the ad report; a broad,
phrase or auto keyword bids the click-weighted price of the searches it served and loses the product-average cap. The roles
are unchanged."""
import json
import os
import tempfile
import unittest

import plan as planner
import test_plan_lanes as T
from test_plan_lanes import (ASIN, AUTO, BROAD, KEYWORDS, NOW, QUERIES, SEARCH_TERMS, STW, SUGGESTED, TODAY, keyword, make_run,
                             one, product, query, search_term, shared_config)

CONFIG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.json'), encoding='utf-8'))


def served(st, kid):
    return dict(st, KeywordId=kid)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = os.path.join(tmp.name, 'run')

    def plan(self, cfg=None, shared=None, write_out=False, **run):
        make_run(self.run_dir, **run)
        return planner.build(ASIN, cfg or product(), shared or shared_config(), self.run_dir, 'weekly', TODAY, now_utc=NOW)


class SqpPricingTest(Base):

    def sqp(self, **run):
        return self.plan(shared=shared_config(pricing='sqp'), write_out=False, **run)

    def terms(self, out):
        return {t['term']: t for t in out['terms']}

    def test_the_config_prices_on_sqp_and_has_no_raise_count(self):
        self.assertEqual(CONFIG['pricing']['search_conversion'], 'sqp')
        self.assertIsNone(CONFIG['auto']['max_raises'])
        self.assertIsNone(CONFIG['auto']['max_raise_pct'])
        self.assertIs(CONFIG['guards']['day1_switch_off'], False)
        self.assertIs(CONFIG['guards']['readback_switch_off'], False)

    def test_a_search_is_priced_on_its_sqp_conversion_shrunk_toward_its_market(self):
        out = self.sqp()
        t = self.terms(out)['gold cards']   # SQP: 0 purchases on 30 of our clicks
        self.assertEqual(t['price_basis'], 'SQP')
        self.assertAlmostEqual(t['cvr_price'], (0 + 10 * t['market_cvr']) / (30 + 10), places=4)
        self.assertEqual(t['be_cpc'], round(5.0 * t['cvr_price'], 2))

    def test_an_exact_keyword_bids_its_searchs_price_not_its_ad_record(self):
        # strong on SQP (17 purchases on 100 of our clicks), weak on its own ads (2 orders on 63 clicks): the gel pens case
        q = query('gel pens', 3000, 900, 90, 100, 17)
        st = search_term('gel pens', STW, 63, 2, 57)
        kw = keyword('20', 'gel pens', 'exact', STW, 0.30, 63, 2, 57)
        run = dict(queries=QUERIES + [q], search_terms=SEARCH_TERMS + [st], keywords=KEYWORDS + [kw],
                   suggested=dict(SUGGESTED, **{'gel pens': [0.50, 0.70, 0.90]}))
        ad = self.plan(write_out=False, **run)
        sqp = self.sqp(**run)
        p_ad = next(p for p in ad['keyword_plan'] if p['keyword_id'] == '20')
        p_sqp = next(p for p in sqp['keyword_plan'] if p['keyword_id'] == '20')
        price = self.terms(sqp)['gel pens']['cvr_price']
        self.assertAlmostEqual(p_sqp['cvr_used'], round(price, 4), places=4)
        self.assertGreater(p_sqp['cvr_used'], p_ad['cvr_used'])   # the ad record pulled it down before
        self.assertEqual(p_sqp['role'], p_ad['role'])              # the role is unchanged
        self.assertIn("its search's own conversion (SQP", p_sqp['price_note'])

    def test_a_search_with_no_sqp_clicks_falls_back_to_the_ad_report(self):
        out = self.sqp()
        t = self.terms(out)['random search']   # no SQP row: 3 ad clicks, no order
        self.assertNotIn('SQP', t['price_basis'])
        self.assertEqual(t['cvr_price'], t['cvr_est'])

    def test_a_broad_keyword_bids_the_searches_it_served_with_no_product_average_cap(self):
        # 'cards' broad served 'thank you cards' (strong on SQP) 30 times and 'gold cards' 10 times
        sts = [s for s in SEARCH_TERMS] + [served(search_term('thank you cards', BROAD, 30, 1, 15), '4'),
                                          served(search_term('gold cards', BROAD, 10, 0, 5), '4')]
        out = self.sqp(search_terms=sts)
        t = self.terms(out)
        p = next(p for p in out['keyword_plan'] if p['keyword_id'] == '4')
        want = (30 * t['thank you cards']['cvr_price'] + 10 * t['gold cards']['cvr_price']) / 40
        self.assertAlmostEqual(p['cvr_used'], round(want, 4), places=4)
        self.assertEqual(p['role'], 'Discovery')
        self.assertIn('of the searches it served', p['action'])
        self.assertNotIn('capped at the product average', p['action'])
        self.assertIn('40 clicks on 2 searches', p['price_note'])
        # with the ad rule it was capped at the product's average breakeven click
        ad = self.plan(write_out=False, search_terms=sts)
        self.assertIn('capped at the product average', next(p for p in ad['keyword_plan'] if p['keyword_id'] == '4')['action'])

    def test_a_broad_keyword_with_under_10_served_clicks_keeps_the_rule_before(self):
        # one click on a thin search must not set the price (decision 165 removed the +25% step that softened it)
        sts = [s for s in SEARCH_TERMS] + [served(search_term('thank you cards', BROAD, 9, 1, 5), '4')]
        p = next(p for p in self.sqp(search_terms=sts)['keyword_plan'] if p['keyword_id'] == '4')
        self.assertNotIn('of the searches it served', p['action'])
        self.assertIsNone(p.get('price_note'))

    def test_a_broad_keyword_that_served_nothing_keeps_the_rule_before(self):
        out = self.sqp()
        p = next(p for p in out['keyword_plan'] if p['keyword_id'] == '5')   # 'greeting cards' phrase, no linked search
        self.assertNotIn('of the searches it served', p['action'])
        self.assertIsNone(p.get('price_note'))

    def test_the_bid_row_says_what_it_was_priced_on(self):
        out = self.sqp()
        row = one(out, 'Bid change', keyword_id='3')   # gold cards exact
        self.assertIn("Priced on its search's own conversion (SQP", row['why'])
        self.assertIn('(decision 162)', row['why'])


class RaiseCountTest(Base):
    def test_no_count_cap_lets_every_validated_raise_through(self):
        extra = [keyword('10', 'card style', 'broad', BROAD, 0.30, 10, 1, 6)]
        capped = self.plan(cfg=product(auto=dict(AUTO, max_raises=1)), keywords=KEYWORDS + extra, write_out=False)
        self.assertTrue([x for x in capped['changes'] if 'used up its' in (x.get('lane_reason') or '')])
        free = self.plan(cfg=product(auto=dict(AUTO, max_raises=None)), keywords=KEYWORDS + extra, write_out=False)
        self.assertFalse([x for x in free['changes'] if 'used up its' in (x.get('lane_reason') or '')])
        raises = [x for x in free['changes'] if T.is_raise(x) and x['lane'] == 'auto']
        self.assertGreater(len(raises), 1)
        # each raise still keeps its +25% step
        row = one(free, 'Bid change', keyword_id='4')
        self.assertEqual(row['new'], 0.37)


    def test_no_step_takes_a_raise_to_its_price_in_one_run(self):
        # decision 165 (2026-10-29): max_raise_pct null, no +25% step
        stepped = one(self.plan(), 'Bid change', keyword_id='4')
        self.assertEqual(stepped['new'], 0.37)   # 0.30 + 25%
        free = one(self.plan(cfg=product(auto=dict(AUTO, max_raise_pct=None))), 'Bid change', keyword_id='4')
        self.assertEqual(free['lane'], 'auto')
        self.assertGreater(free['new'], 0.37)
        self.assertEqual(free['new'], free.get('new_proposed', free['new']))
        self.assertIsNone(free.get('new_capped'))


if __name__ == '__main__':
    unittest.main()
