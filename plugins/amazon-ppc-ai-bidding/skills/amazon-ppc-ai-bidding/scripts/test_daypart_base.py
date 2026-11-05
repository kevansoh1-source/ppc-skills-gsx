"""Decision 146 (Kim, 2026-10-26): a Scale Insights dayparting modifier still in Amazon's live bids (rule 203's weekend
-40%, there until the weekday hours open) is read back to the base bid before the plan compares anything against it.

Built on test_price_everything's synthetic run (test_plan_lanes' make_run plus live reads)."""
import unittest

import daypart_base as D
import test_plan_lanes as T
import test_price_everything as P

EXTRA = [T.keyword(str(20 + i), f'extra cards {i}', 'phrase', T.BROAD, 0.40, 0, 0, 0) for i in range(4)]
KEYWORDS = T.KEYWORDS + EXTRA   # 12 keywords with a Scale Insights row


def live(factor, rows=KEYWORDS):
    return [P.live_keyword(k['KeywordId'], k['Keyword'], k['MatchType'], k['CampaignName'], round(k['Bid'] * factor, 2))
            for k in rows]


class DetectTest(unittest.TestCase):
    def test_live_bids_that_are_the_stored_ones_carry_no_modifier(self):
        self.assertEqual(D.detect([(0.5, 0.5)] * 9 + [(0.5, 0.7)] * 2), (1.0, 'none'))

    def test_one_common_factor_on_most_rows_is_the_modifier(self):
        pairs = [(s, round(s * 0.6, 2)) for s in (0.3, 0.45, 0.8, 1.05, 0.25, 0.5, 0.62, 0.9, 1.5, 0.4)] + [(0.5, 0.71)]
        self.assertEqual(D.detect(pairs), (0.6, 'modifier'))

    def test_scattered_differences_after_a_write_are_mixed_not_a_modifier(self):
        # a weekday re-plan after this morning's writes, before Scale Insights synced: the written rows differ every which way
        pairs = [(0.5, 0.5)] * 6 + [(0.5, 0.31), (0.4, 0.62), (0.8, 0.55), (0.3, 0.44), (0.9, 0.2)]
        self.assertEqual(D.detect(pairs), (1.0, 'mixed'))

    def test_too_few_rows_to_tell_change_nothing(self):
        self.assertEqual(D.detect([(0.5, 0.3)] * 9), (1.0, 'too_few'))

    def test_the_base_is_the_stored_bid_when_it_matches_else_live_over_the_factor(self):
        self.assertEqual(D.base(0.25, 0.15, 0.6), 0.25)
        self.assertEqual(D.base(0.25, 0.30, 0.6), 0.5)    # written since Scale Insights synced
        self.assertEqual(D.base(0.30, 0.30, 0.6), 0.3)    # written, taken as the base, modifier not yet back on it
        self.assertEqual(D.base(None, 0.18, 0.6), 0.3)    # live only
        self.assertEqual(D.base(None, 0.01, 0.6), 0.02)   # never under Amazon's minimum
        self.assertEqual(D.base(0.25, 0.15, 1.0), 0.15)


class PlannerTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp
    plan = T.PlannerLanesTest.plan
    build = P.PriceEverythingTest.build

    def test_the_weekend_modifier_is_read_back_to_the_base_before_planning(self):
        out = self.build(live_keywords=live(0.6) + [P.live_keyword('30', 'fresh cards', 'phrase', T.BROAD, 0.18)],
                         keywords=KEYWORDS)
        daypart = out['summary'][0]['inventory']['daypart']
        self.assertEqual((daypart['status'], daypart['factor'], daypart['keywords']), ('modifier', 0.6, 13))
        bids = {p['keyword_id']: p['bid'] for p in out['keyword_plan']}
        for k in KEYWORDS:
            self.assertEqual(bids[k['KeywordId']], k['Bid'], k['Keyword'])
        self.assertEqual(bids['30'], 0.3)
        # the cut on the $1.50 broad keyword runs from its base, not from the $0.90 Amazon showed under the modifier
        self.assertEqual(T.one(out, 'Bid change', keyword_id='5')['current'], 1.5)

    def test_a_changed_weekend_cut_is_priced_from_the_full_bid_too(self):
        # Kim, 2026-10-26: "I might tweak it to -20% or -25%" -- the factor comes from the bids, never from config.json,
        # so a -25% weekend is read back to the full bid (no "double minus") and the plan says config needs updating
        out = self.build(live_keywords=live(0.75), keywords=KEYWORDS)
        daypart = out['summary'][0]['inventory']['daypart']
        self.assertEqual((daypart['status'], daypart['factor']), ('modifier', 0.75))
        self.assertEqual(daypart['config_differs']['configured'], [0.8])
        bids = {p['keyword_id']: p['bid'] for p in out['keyword_plan']}
        for k in KEYWORDS:
            self.assertEqual(bids[k['KeywordId']], k['Bid'], k['Keyword'])
        self.assertNotIn('config_differs', self.build(live_keywords=live(0.8), keywords=KEYWORDS)['summary'][0]['inventory']['daypart'])

    def test_a_bid_written_under_the_modifier_keeps_its_written_base(self):
        # B0SAMP0015, 2026-10-26 18:15 SGT: Scale Insights took the 16:10 writes as its stored bids, and Amazon still shows
        # the written bid, the modifier not yet back on it; the other keywords read stored x 0.60
        rows = live(0.6)
        rows[0]['bid'] = KEYWORDS[0]['Bid']
        rows[4]['bid'] = KEYWORDS[4]['Bid']
        out = self.build(live_keywords=rows, keywords=KEYWORDS)
        self.assertEqual(out['summary'][0]['inventory']['daypart']['status'], 'modifier')
        bids = {p['keyword_id']: p['bid'] for p in out['keyword_plan']}
        for k in KEYWORDS:
            self.assertEqual(bids[k['KeywordId']], k['Bid'], k['Keyword'])

    def test_live_bids_with_no_modifier_are_used_as_read(self):
        rows = live(1.0)
        rows[3]['bid'] = 0.45   # written since Scale Insights synced: the live bid is the base
        out = self.build(live_keywords=rows, keywords=KEYWORDS)
        daypart = out['summary'][0]['inventory']['daypart']
        self.assertEqual((daypart['status'], daypart['factor'], daypart['keywords']), ('none', 1.0, 0))
        self.assertEqual(next(p['bid'] for p in out['keyword_plan'] if p['keyword_id'] == '4'), 0.45)


if __name__ == '__main__':
    unittest.main()
