"""The brand is organic only (Kim, 2026-10-20: "YourBrand as the brand should be left to organic"; config.json
scale_insights.blacklist_keep). On 2026-10-26 the rollout run made "yourbrand birthday cards" an Invest search on
B0SAMP0014, launched its exact campaign and took "yourbrand" off the blacklist; it was live 14 minutes before it was
reversed by hand. These tests pin the guard: a search holding the brand is never invested in, held at breakeven, tested
at a raise or whitelisted, whatever the ladder says, and a last sweep drops any row that would.

Built on test_plan_lanes' synthetic run (make_run): "yourbrand cards" gets the same numbers as "blank cards", which the
ladder promotes.
"""
import copy
import unittest

import blacklist_rescue
import plan as planner
import test_plan_lanes as T

BRAND = 'yourbrand cards'
QUERIES = T.QUERIES + [T.query(BRAND, 2000, 800, 80, 30, 6)]
SEARCH_TERMS = T.SEARCH_TERMS + [T.search_term(BRAND, T.STW, 20, 4, 12)]
SUGGESTED = dict(T.SUGGESTED, **{BRAND: [0.55, 0.70, 0.90]})


def brand(t):
    return blacklist_rescue.brand_search(t, ['yourbrand'])


class BrandSearchTest(unittest.TestCase):
    def test_a_brand_search_is_any_search_holding_the_brand_word(self):
        self.assertEqual(brand('yourbrand'), 'yourbrand')
        self.assertEqual(brand('yourbrand birthday cards'), 'yourbrand')
        self.assertEqual(brand('Birthday Cards YourBrand'), 'yourbrand')
        self.assertIsNone(brand('birthday cards'))
        self.assertIsNone(brand('decorable cards'))
        self.assertIsNone(blacklist_rescue.brand_search('yourbrand cards', []))

    def test_the_rescue_never_frees_or_whitelists_the_brand(self):
        lists = dict(NegativeExactList=['yourbrand birthday card', 'blank card'], NegativePhraseList=['yourbrand', 'blank'],
                     ExactWhiteList=[], PhraseWhiteList=[])
        out = blacklist_rescue.rescue(['yourbrand birthday cards', 'blank cards'], lists, ['yourbrand'])
        self.assertEqual(out['exact_remove'], ['blank card'])
        self.assertEqual(out['phrase_remove'], ['blank'])
        self.assertEqual(out['whitelist_add'], ['blank cards'])


class BrandGuardPlanTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp
    plan = T.PlannerLanesTest.plan

    def test_a_brand_search_that_beats_the_market_is_never_promoted(self):
        out = self.plan(queries=QUERIES, search_terms=SEARCH_TERMS, suggested=SUGGESTED)
        term = next(t for t in out['terms'] if t['term'] == BRAND)
        self.assertEqual((term['role'], term['sub_role'], term['brand']), ('Leave', 'Leave', 'yourbrand'))
        self.assertIn('organic only', term['why'])
        self.assertEqual([x for x in out['changes'] if x.get('keyword') == BRAND], [])
        T.one(out, 'New exact campaign', keyword='blank cards')   # the same numbers on a non-brand search still promote
        guard = out['summary'][0]['brand_guard']
        self.assertEqual(guard['words'], ['yourbrand'])
        self.assertEqual([s['search'] for s in guard['searches']], [BRAND])
        self.assertIn(guard['searches'][0]['was'], ('Invest', 'Prove first'))
        self.assertEqual(guard['dropped_rows'], [])

    def test_a_brand_keyword_is_cut_but_never_raised(self):
        keywords = T.KEYWORDS + [T.keyword('20', BRAND, 'exact', T.STW, 0.10, 20, 4, 3),         # converts well, low bid
                                 T.keyword('21', 'yourbrand', 'broad', T.BROAD, 0.05, 10, 2, 1),   # Discovery would raise
                                 T.keyword('22', 'yourbrand gift cards', 'exact', T.STW, 2.00, 10, 0, 9)]  # a cut stays
        out = self.plan(queries=QUERIES, search_terms=SEARCH_TERMS, suggested=SUGGESTED, keywords=keywords)
        plan_rows = {p['keyword_id']: p for p in out['keyword_plan']}
        for kid, bid in (('20', 0.10), ('21', 0.05)):
            self.assertEqual(plan_rows[kid]['new_bid'], bid)
            self.assertIn('brand search: organic only, never raised', plan_rows[kid]['action'])
        self.assertEqual([x for x in out['changes'] if x.get('keyword_id') in ('20', '21')], [])
        cut = T.one(out, 'Bid change', keyword_id='22')
        self.assertLess(cut['new'], cut['current'])

    def test_a_logged_prove_first_on_the_brand_is_not_kept_a_rank_term(self):
        # the invest log's retained Prove first (section 1a) would keep it a rank term; the brand pass comes after it
        cfg = T.product(invest_log={'yourbrand birthday cards': dict(role='Prove first', since='2026-10-01')})
        out = self.plan(cfg=cfg, search_terms=SEARCH_TERMS + [T.search_term('yourbrand birthday cards', T.STW, 4, 1, 3)])
        term = next(t for t in out['terms'] if t['term'] == 'yourbrand birthday cards')
        self.assertEqual(term['role'], 'Leave')
        self.assertEqual([x for x in out['changes'] if 'yourbrand' in str(x.get('keyword'))], [])

    def test_the_blacklist_rescue_keeps_the_brand_in_the_plan(self):
        lists = dict(NegativeExactList=[], NegativePhraseList=['yourbrand'], ExactWhiteList=[], PhraseWhiteList=[],
                     _read='test')
        cfg = T.product(invest_log={'yourbrand birthday cards': dict(role='Invest', since='2026-10-01')})
        out = self.plan(cfg=cfg, queries=QUERIES, search_terms=SEARCH_TERMS, suggested=SUGGESTED,
                        extra={'si_blacklist.json': lists})
        for x in T.by_type(out, 'Scale Insights setup'):
            self.assertNotIn('yourbrand', x.get('phrase_remove') or [])
            self.assertFalse([w for w in x.get('whitelist_add') or [] if 'yourbrand' in w])

    def test_the_guard_reads_the_brand_from_config(self):
        shared = T.shared_config()
        shared['scale_insights'] = dict(shared['scale_insights'], blacklist_keep=[])
        out = self.plan(shared=shared, queries=QUERIES, search_terms=SEARCH_TERMS, suggested=SUGGESTED)
        T.one(out, 'New exact campaign', keyword=BRAND)   # no brand configured: no guard


class BrandSweepTest(unittest.TestCase):
    def test_the_sweep_drops_every_row_that_builds_funds_frees_or_raises_the_brand(self):
        changes = [dict(type='New exact campaign', keyword='yourbrand birthday cards'),
                   dict(type='New SB video campaign', keyword='yourbrand birthday cards'),
                   dict(type='Budget and top of search', keyword='yourbrand birthday cards', current='$5', new='$10'),
                   dict(type='Scale Insights setup', keyword='yourbrand birthday cards'),
                   dict(type='Bid change', keyword='yourbrand cards', current=0.40, new=0.55),
                   dict(type='SB bid change', keyword='yourbrand cards', current=0.40, new=0.55),
                   dict(type='Scale Insights setup', keyword='blacklist rescue', phrase_remove=['yourbrand', 'blank'],
                        whitelist_add=['blank cards']),
                   dict(type='Bid change', keyword='yourbrand cards', current=0.55, new=0.40),   # a cut: kept
                   dict(type='Pause keyword', keyword='yourbrand cards', current=0.55, new=0),   # kept
                   dict(type='New exact campaign', keyword='blank cards'),                       # not the brand: kept
                   dict(type='Scale Insights setup', keyword='blacklist rescue', phrase_remove=['blank'])]
        kept = copy.deepcopy(changes[7:])
        dropped = planner.brand_sweep(changes, brand)
        self.assertEqual(changes, kept)
        self.assertEqual(len(dropped), 7)
        self.assertTrue(all(d['why'] for d in dropped))


if __name__ == '__main__':
    unittest.main()
