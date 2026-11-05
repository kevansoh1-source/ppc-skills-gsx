import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

import human_review
import market_review
from test_human_review import SHARED, sample

ASIN = 'B0SAMP0025'
DATE = '2026-10-18'


def fixture():
    term = dict(sample(), term='animal bookmarks', sqp_volume=2800, observed_days=84)
    plan = dict(summary=[dict(asin=ASIN)], terms=[term], terms_window='2026-07-26 to 2026-10-17')
    product = dict(asin=ASIN, price=7.99)
    items = human_review.propose(plan, product, SHARED, DATE)
    offer = dict(asin=ASIN, title='Test pack', effective_price=8, pack_count=20, unit='bookmark', comparison='Same format, pack and material',
                 availability='in_stock', discount_terms='No coupon observed', rating_context='4.5 stars; 100 reviews',
                 url='https://www.amazon.com/dp/' + ASIN, observed_on=DATE, comparable=True, query='animal bookmarks')
    research = dict(asin=ASIN, as_of=DATE, own_offer=offer,
                    competitors=[dict(offer, asin='B000000001', url='https://www.amazon.com/dp/B000000001', effective_price=10),
                                 dict(offer, asin='B000000002', url='https://www.amazon.com/dp/B000000002', effective_price=12)],
                    queries=[dict(query='animal bookmarks', relevance='direct', reason='Product depicts animals on bookmarks', source='Verified listing title and images')],
                    searches=[dict(query='animal bookmarks', url='https://www.amazon.com/s?k=animal+bookmarks', observed_on=DATE,
                                   findings='Comparable animal bookmark packs', result_mix='Organic packs; sponsored results recorded separately')],
                    assessment=dict(conversion_verdict='listing_candidate', price_verdict='underpriced', rationale='Test fixture rationale, not a real recommendation',
                                    counterevidence='Review count and delivery differ', recommendation='Review gallery hypothesis and price scenario', confidence='medium'))
    return plan, product, items, research


def bid_item():
    """A run's Bids item, as plan.py main puts it in plan.json['human_review'] after market_review.assess has run."""
    row = dict(row_id='Bid change:1', type='Bid change', approval_required='owner', lane='auto')
    return human_review.validate([dict(id='bids-2026-10-18', kind='bid', title='1 change to agree or refuse (shadow run)',
                                       reason='r', action='a', source='s', window='w', shadow=True, locked_count=0,
                                       ai_review=dict(phase='human_ready'), rows=[row])])[0]


class MarketReviewTests(unittest.TestCase):
    def assess(self, research_change=None):
        plan, product, items, research = fixture()
        if research_change:
            research_change(research)
        return market_review.assess(items, plan, product, SHARED, DATE, research)

    def test_score_and_unit_prices_computed_not_trusted(self):
        review = self.assess()[0]['ai_review']
        self.assertEqual(review['phase'], 'human_ready')
        self.assertAlmostEqual(review['opportunities'][0]['opportunity'], 600)
        self.assertEqual(review['own_offer']['unit_price'], 0.4)
        self.assertAlmostEqual(review['price_context']['median_unit_price'], 0.55)

    def test_missing_research_never_escalates(self):
        plan, product, items, research = fixture()
        result = market_review.assess(items, plan, product, SHARED, DATE)
        self.assertTrue(all(item['ai_review']['phase'] == 'research' for item in result))
        self.assertIsNone(result[0]['ai_review']['opportunities'][0]['opportunity'])

    def test_broad_weakness_cannot_diagnose_listing(self):
        result = self.assess(lambda research: research['queries'][0].update(relevance='broad'))
        self.assertEqual(result[0]['ai_review']['phase'], 'research')
        self.assertEqual(result[0]['ai_review']['direct_weak_count'], 0)
        self.assertIsNone(result[0]['ai_review']['opportunities'][0]['opportunity'])

    def test_thin_samples_and_missing_volume_not_scored(self):
        plan, product, items, research = fixture()
        plan['terms'].append(dict(plan['terms'][0], term='thin', sqp_our_clicks=3))
        rows = market_review.opportunities(plan, research, SHARED['thresholds'])
        self.assertEqual(len(rows), 1)
        plan['terms'][0]['observed_days'] = None
        self.assertIsNone(market_review.opportunities(plan, research, SHARED['thresholds'])[0]['opportunity'])

    def test_zero_sqp_volume_is_not_a_missing_volume_gap(self):
        gap = 'Dated SQP search volume and observed days for relevant sampled queries.'
        plan, product, items, research = fixture()
        plan['terms'][0]['sqp_volume'] = 0
        result = market_review.assess(items, plan, product, SHARED, DATE, research)
        self.assertNotIn(gap, result[0]['ai_review']['missing'])
        self.assertEqual(result[0]['ai_review']['opportunities'][0]['monthly_searches'], 0.0)
        plan['terms'][0]['sqp_volume'] = None
        result = market_review.assess(items, plan, product, SHARED, DATE, research)
        self.assertIn(gap, result[0]['ai_review']['missing'])

    def test_comparable_offers_must_be_distinct_current_and_in_stock(self):
        for field, value in [('asin', ASIN), ('observed_on', '2026-10-17'), ('availability', 'out_of_stock'), ('effective_price', float('nan')),
                             ('unit', 'card'), ('url', 'javascript:alert(1)'), ('query', 'irrelevant')]:
            with self.subTest(field=field):
                result = self.assess(lambda research: research['competitors'][0].update({field: value}))
                self.assertEqual(result[1]['ai_review']['phase'], 'research')

    def test_stale_or_wrong_asin_research_rejected(self):
        for field, value in [('asin', 'B000000099'), ('as_of', '2026-10-17')]:
            with self.assertRaises(ValueError):
                self.assess(lambda research: research.update({field: value}))

    def test_wrong_plan_asin_rejected(self):
        plan, product, items, research = fixture()
        plan['summary'][0]['asin'] = 'B000000099'
        with self.assertRaises(ValueError):
            market_review.assess(items, plan, product, SHARED, DATE, research)

    def test_direct_weakness_not_dismissed_as_broad_mismatch(self):
        result = self.assess(lambda research: research['assessment'].update(conversion_verdict='query_mismatch'))
        self.assertEqual(result[0]['ai_review']['phase'], 'research')

    def test_same_volume_days_and_relevance_tiers(self):
        plan, product, items, research = fixture()
        plan['terms'].append(dict(plan['terms'][0], term='gifts', sqp_volume=100000, observed_days=30))
        research['queries'].append(dict(query='gifts', relevance='adjacent', reason='Possible use, not exact format', source='Listing'))
        rows = market_review.opportunities(plan, research, SHARED['thresholds'])
        self.assertEqual(rows[0]['query'], 'animal bookmarks')
        self.assertGreater(rows[1]['opportunity'], rows[0]['opportunity'])

    def test_low_confidence_uncertain_price_stays_in_research(self):
        result = self.assess(lambda research: research['assessment'].update(price_verdict='uncertain', confidence='low'))
        self.assertEqual(result[1]['ai_review']['phase'], 'research')

    def test_fair_price_monitored_not_deleted(self):
        result = self.assess(lambda research: research['assessment'].update(price_verdict='fair'))
        self.assertEqual(result[1]['ai_review']['phase'], 'monitor')
        self.assertEqual(result[1]['status'], 'open')

    def test_later_sweep_invalidates_old_research_preserves_history(self):
        ready = self.assess()[0]
        ready['owner'] = 'Lee'
        incoming = copy.deepcopy(ready)
        incoming.pop('ai_review')
        merged = human_review.merge([ready], [incoming], '2026-10-19')[0]
        self.assertEqual(merged['owner'], 'Lee')
        self.assertEqual(merged['ai_review']['phase'], 'research')

    # --- Task 7, R7: a bid item has no listing or price evidence to gate -----------------------------------------
    def test_assess_leaves_bid_items_untouched(self):
        plan, product, items, research = fixture()
        bid = bid_item()
        for research_arg in (research, None):
            with self.subTest(research=research_arg is not None):
                result = market_review.assess(items + [bid], plan, product, SHARED, DATE, research_arg)
                self.assertEqual(len(result), 3)
                self.assertEqual(result[-1], bid)  # no price-branch gaps, no phase change, no market evidence attached
                self.assertIsNot(result[-1], bid)  # a copy, like the other items
        self.assertEqual(bid, bid_item())  # the input was not changed
        self.assertEqual(market_review.assess(items, plan, product, SHARED, DATE)[0]['ai_review']['phase'], 'research')

    def test_the_cli_leaves_bid_items_untouched(self):
        plan, product, items, research = fixture()
        bid = bid_item()
        plan['human_review'] = items + [bid]
        with tempfile.TemporaryDirectory() as tmp:
            paths = {name: os.path.join(tmp, name + '.json') for name in ('plan', 'product', 'out')}
            for name, data in (('plan', plan), ('product', product)):
                with open(paths[name], 'w', encoding='utf-8') as fh:
                    json.dump(data, fh)
            argv = ['market_review.py', '--plan', paths['plan'], '--product', paths['product'], '--date', DATE, '--out', paths['out']]
            with unittest.mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                market_review.main()
            with open(paths['out'], encoding='utf-8') as fh:
                written = json.load(fh)
        self.assertEqual(written[-1], bid)
        self.assertEqual([item['kind'] for item in written], ['listing', 'price', 'bid'])
        self.assertEqual(written[0]['ai_review']['phase'], 'research')  # the listing item is still assessed


if __name__ == '__main__':
    unittest.main()
