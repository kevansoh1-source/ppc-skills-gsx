"""Product fit wins over generic protection and attributed orders (2026-10-24)."""
import os
import unittest
from unittest.mock import patch

import plan as planner
import test_plan_lanes as T


WRONG = '5x7 thank you cards with envelopes'
RIGHT = '4x6 thank you cards with envelopes'
GENERIC = 'thank you cards with envelopes'


class ProductSizeTest(unittest.TestCase):
    def build(self, size='6x4in (=4x6)', asin=T.ASIN, **over):
        searches = [WRONG, RIGHT, GENERIC]
        cfg = T.product(relevance={'protect': ['thank you', 'with envelopes'],
                                   'negate_phrase': {'5x7': 'wrong size'}})
        if size is not None:
            cfg['size'] = size
        cfg.update(over)
        inputs = ({t: T.query(t, 2000, 800, 80, 30, 6) for t in searches},
                  [T.search_term(t, T.STW, 20, 3, 12) for t in searches],
                  [T.keyword(str(i), t, 'exact', T.STW, .5, 20, 3, 12) for i, t in enumerate(searches)],
                  {t: [.5, .7, .9] for t in searches},
                  [T.campaign(T.STW)], {}, {}, '2026-10-12')
        # Exercise the real planner and lanes on in-memory report inputs; no fixture files or connectors.
        with patch.object(planner, 'load_inputs', return_value=inputs), \
                patch.object(planner.os.path, 'exists', side_effect=lambda p: os.path.basename(p) == 'si_blacklist.json'), \
                patch.object(planner, 'load_lane_inputs', return_value=T.FRESH_LANE_INPUTS), \
                patch.object(planner.blacklist_rescue, 'load_lists', return_value={'NegativeExactList': [WRONG]}):
            return planner.build(asin, cfg, T.shared_config(), 'unused-size-test-run', 'onboard', T.TODAY, T.NOW)

    def test_wrong_size_beats_protection_and_three_orders(self):
        out = self.build()
        term = next(t for t in out['terms'] if t['term'] == WRONG)
        self.assertEqual(term['role'], 'Negate')
        self.assertIn('5x7', term['why'])
        self.assertIn('4x6', term['why'])
        self.assertNotIn(WRONG, [r['keyword'] for r in out['rerank']])
        rows = [r for r in out['changes'] if r.get('keyword') == WRONG]
        self.assertTrue(rows)
        self.assertTrue(all(r['lane'] == 'monitor' for r in rows))
        self.assertFalse(any(r['type'] == 'New exact campaign' for r in rows))
        self.assertEqual(out['harvest']['priced_searches'], 2)

    def test_own_size_and_no_size_search_still_promote(self):
        out = self.build()
        promoted = [r['keyword'] for r in T.by_type(out, 'New exact campaign')]
        self.assertIn(RIGHT, promoted)
        self.assertIn(GENERIC, promoted)

    def test_unknown_product_size_keeps_behavior_and_reports_once(self):
        out = self.build(size=None)
        self.assertIn(WRONG, [r['keyword'] for r in T.by_type(out, 'New exact campaign')])
        self.assertIn('unknown', out['summary'][0]['size_check']['note'])

    @unittest.skip('needs files from the original account')
    def test_fingerprint_supplies_size_without_product_edit(self):
        sizes = planner.product_sizes('B0SAMP0003', {})
        irrelevant = planner.make_irrelevant('B0SAMP0003', {'protect': ['thank you']}, sizes)
        self.assertIn('4x6', irrelevant(WRONG))
        self.assertIsNone(irrelevant(RIGHT))

    def test_order_spacing_units_and_decimals(self):
        for size, own, wrong in [
            ('6x4in (=4x6)', ['4x6', '6 x 4', '4X6in', '6x4inch', '4 inches x 6 inches', '4"x6"', '4 × 6'],
             ['5x7', '5 x 7', '5x7in', '5x7inch', '8.5x11', '8.5 x 4.25in']),
            ('8.5 x 4.25in', ['4.25x8.5inch', '8.50 x 4.250'], ['8.5x11', '4x6'])]:
            sizes = planner.product_sizes(T.ASIN, {'size': size})
            check = planner.make_irrelevant(T.ASIN, {'protect': ['thank you']}, sizes)
            for token in own:
                with self.subTest(size=size, own=token):
                    self.assertIsNone(check(token + ' thank you cards'))
            for token in wrong:
                with self.subTest(size=size, wrong=token):
                    self.assertIn('Wrong size', check(token + ' thank you cards'))
            self.assertIsNone(check(GENERIC))

    def test_multiple_product_sizes_and_mixed_query(self):
        check = planner.make_irrelevant(T.ASIN, {}, planner.product_sizes(T.ASIN, {'size': '4x6 and 5x7in'}))
        self.assertIsNone(check('7x5 thank you cards'))
        self.assertIn('8x10', check('4x6 or 8x10 thank you cards'))

    def test_a_protected_size_is_a_decision_not_a_generic_phrase(self):
        # Get Well cards (4x6) protect '5x7' on purpose: its 5x7 searches convert (logs/2026-10-23-get-well-cards-
        # onboarding-preflight.md). A protect entry naming a size allows that size; 'thank you' does not
        cfg = {'size': '4x6in', 'relevance': {'protect': ['thank you', '5x7']}}
        check = planner.make_irrelevant(T.ASIN, cfg['relevance'], planner.product_sizes(T.ASIN, cfg))
        self.assertIsNone(check('5x7 thank you cards'))
        self.assertIn('8x10', check('8x10 thank you cards'))
        out = self.build(relevance={'protect': ['thank you', 'with envelopes', '5x7']})
        self.assertNotEqual(next(t for t in out['terms'] if t['term'] == WRONG)['role'], 'Negate')
        self.assertEqual([tuple(s) for s in out['summary'][0]['size_check']['protected']], [(5.0, 7.0)])

    def test_only_a_bid_cut_goes_out_for_a_wrong_size_search(self):
        # a bid cut only lowers spend and is reversible, so it keeps its lane; a pause is held too: the size comes from
        # the fingerprint, which can be approximate (the notebooks' 8.5x11 is their size, decision 61)
        rows = [dict(type='Bid change', keyword=WRONG, current=1.0, new=0.5),
                dict(type='Pause keyword', keyword=WRONG, current=1.0, new=None),
                dict(type='SB pause keyword', keyword=WRONG, current=0.8, new=None),
                dict(type='Bid change', keyword=WRONG, current=0.5, new=0.9),
                dict(type='New exact campaign', keyword=WRONG),
                dict(type='Budget and top of search', keyword=WRONG),
                dict(type='Bid change', keyword=RIGHT, current=0.5, new=0.9)]
        planner.size_holds(rows, planner.product_sizes(T.ASIN, {'size': '4x6in'}))
        self.assertEqual([bool(r.get('relevance_hold')) for r in rows], [False, True, True, True, True, True, False])
        self.assertIn('5x7', rows[3]['why'])

    def test_wrong_size_in_old_invest_log_is_not_rescued(self):
        out = self.build(invest_log={WRONG: {'role': 'Invest', 'since': T.TODAY}})
        self.assertEqual(out['summary'][0]['blacklist_rescue']['exact_remove'], 0)
        for row in out['changes']:
            self.assertNotIn(WRONG, row.get('whitelist_add', []))


if __name__ == '__main__':
    unittest.main()
