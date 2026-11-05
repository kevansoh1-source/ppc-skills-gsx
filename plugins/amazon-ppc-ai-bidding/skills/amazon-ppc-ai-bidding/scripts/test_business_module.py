"""The planner's business sections in their own module, business.py (plan docs/superpowers/plans/2026-10-22-business-module.md,
Task 1): the module's functions are there, plan.py keeps the old names of the two it used to hold, and a product with no
Amazon Business (B2B) campaign plans as it did, with nothing in its business summary.

Task 2 folded the loops the move duplicated: one funnel-negatives loop and one evidence text for both shopper kinds. Their
tests pin what the two loops wrote before the fold, as literals captured from the code at 9157157.
"""
import os
import tempfile
import unittest

import business
import plan as planner
import test_business_roles as R
import test_plan_lanes as T

FUNCTIONS = ('pool', 'records', 'bid_pull', 'owners_and_homes', 'price', 'promotion_rows', 'new_keyword_rows',
             'funnel_negatives', 'scale_insights_row', 'stop_loss', 'rerank_rows', 'campaign_rows', 'stamp_campaigns',
             'summary')
COUNTS = ('campaigns', 'keywords', 'bid_changes', 'pauses', 'invest', 'prove_first', 'copies_paused', 'negatives',
          'new_keywords', 'stop_loss_reviews', 'si_rows',
          'stop_loss_step_downs')  # the step-downs the run writes itself (autonomous runs, 2026-10-22)

# two campaigns named like an exact SKC whose own keyword is a close variant of an invest search: a consumer one (zebra
# card) and a B2B one (office card)
CV_SKC = f'Cards - {T.ASIN} - Exact SKC - zebra card - TOS Rank'
B2B_CV_SKC = f'Cards - {T.ASIN} - B2B - Exact SKC - office card - TOS Rank'
T.IDS[CV_SKC] = ('112', '212')
T.IDS[B2B_CV_SKC] = ('113', '213')
B2B_AD_GROUPS = {'208', '209', '210', '211', '213'}

# the roles fixture's funnel negatives and skipped negatives with FUNNEL_TERMS added, (keyword, ad group, owner_kind, why)
# in plan order, as the two loops wrote them before the fold (captured at 9157157)
CONSUMER_WHY = 'This ad group paid for the search in the last 90 days; the exact campaign owns it from now on.'
BUSINESS_WHY = ("Amazon Business campaign: priced on the B2B campaigns' own conversion (14% pooled, 10-click prior), never "
                "on the consumer search. This B2B ad group paid for the search in the last 90 days; the business owner "
                "holds it from now on.")
NEGATIVES = [('blank cards', '201', None, CONSUMER_WHY), ('blank cards', '202', None, CONSUMER_WHY),
             ('thank you cards', '202', None, CONSUMER_WHY), ('zebra cards', '201', None, CONSUMER_WHY),
             ('office cards', '201', None, CONSUMER_WHY), ('office cards', '209', 'business', BUSINESS_WHY),
             ('zebra cards', '209', 'business', BUSINESS_WHY)]
SKIPPED = [('zebra cards', '205', None, 'inside another exact SKC; Amazon close-variant matching makes this risky'),
           ('zebra cards', '212', None,
            'close variant of the exact SKC\'s own keyword "zebra card": a negative here would switch that SKC off'),
           ('zebra cards', '211', 'business', 'inside a B2B exact campaign; Amazon close-variant matching makes this risky'),
           ('office cards', '213', 'business',
            'close variant of the B2B exact campaign\'s own keyword "office card": a negative here would switch it off')]

# the evidence the two texts wrote for 'zebra cards' in the roles fixture before the fold (captured at 9157157). A consumer
# rank term's text ends with where its index and volume came from (data-stage design 4.4, merged 2026-10-22); a business
# record's does not
ZEBRA_EVIDENCE = 'index 2.00 (SQP); SQP 5 purchases on 20 of our clicks; 600 searches in 12 weeks; basis: SQP; volume: SQP'
ZEBRA_BUSINESS_EVIDENCE = 'index 2.41 (B2B search-term report); B2B ads 7 orders on 25 clicks; 600 searches in 12 weeks'


class BusinessModuleTest(unittest.TestCase):
    def test_module_functions_exist(self):
        for name in FUNCTIONS:
            self.assertTrue(callable(getattr(business, name, None)), name)
        # plan.py keeps the names every caller and test used before the move
        self.assertIs(planner.business_campaign_rows, business.campaign_rows)
        self.assertIs(planner.stamp_business_campaigns, business.stamp_campaigns)

    def test_plan_without_business_campaigns_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = T.make_run(os.path.join(tmp, 'run'))
            out = planner.build(T.ASIN, T.product(), T.shared_config(), run, 'weekly', T.TODAY, now_utc=T.NOW)
        summary = out['summary'][0]['business']
        self.assertEqual({k: summary[k] for k in COUNTS}, dict.fromkeys(COUNTS, 0))
        # no B2B keyword row: the pool is its prior, the config's
        prior = T.CONFIG['business']
        self.assertEqual(summary['pooled_cvr'], round(prior['pool_prior_cvr'], 4))
        self.assertEqual(summary['pool_prior'], dict(cvr=round(prior['pool_prior_cvr'], 4), as_of=prior['pool_prior_as_of'],
                                                     source='config'))
        self.assertEqual(sorted(summary), sorted(COUNTS + ('pooled_cvr', 'pool_prior')))
        self.assertEqual(out['business_terms'], [])
        self.assertEqual(out['business_live_invests'], [])
        self.assertEqual(out['business_owners'], [])
        self.assertEqual([x for x in out['changes'] + out['rerank'] + out['stop_loss'] + out['skipped_negatives']
                          if x.get('owner_kind')], [])


class FoldedLoopsTest(unittest.TestCase):
    """Task 2: the consumer and business funnel loops are one loop, and evidence_of / business_evidence_of one text."""
    setUp = T.PlannerLanesTest.setUp
    plan = R.BusinessRolesTest.plan
    shared = staticmethod(R.shared)

    # search-term rows that exercise every exclusion of both kinds: zebra cards (a consumer promotion and a business
    # invest, owner 902 in campaign 108) in the consumer group 201, inside the consumer exact SKC of thank you cards (205),
    # inside a consumer SKC named for its close variant (212), inside the B2B exact campaign 111 (211); office cards (a
    # consumer promotion and a business New exact keyword in 110) inside a B2B SKC named for its close variant (213) and in
    # the consumer group 201. The fixture's B2B rows add zebra and office cards in the B2B phrase group 209 and blank cards
    # (a consumer promotion only) in the B2B group 208
    FUNNEL_TERMS = [T.search_term('zebra cards', T.STW, 6, 2, 3), T.search_term('zebra cards', T.SKC, 3, 0, 2),
                    T.search_term('zebra cards', CV_SKC, 2, 0, 1), T.search_term('zebra cards', R.B2B_EXACT2, 4, 1, 3),
                    T.search_term('office cards', B2B_CV_SKC, 2, 0, 1), T.search_term('office cards', T.STW, 5, 1, 3)]

    def test_funnel_loop_skips_per_kind(self):                              # Review Focus 3
        out = self.plan(search_terms=R.SEARCH_TERMS + self.FUNNEL_TERMS)
        negatives = [(x['keyword'], x['ad_group_id'], x.get('owner_kind'), x['why']) for x in T.by_type(out, 'Negative exact')]
        skipped = [(x['keyword'], x['ad_group_id'], x.get('owner_kind'), x['why']) for x in out['skipped_negatives']]
        self.assertEqual(negatives, NEGATIVES)
        self.assertEqual(skipped, SKIPPED)
        # each kind negates inside its own ad groups only: a consumer search-term row in a B2B ad group (blank cards in 208,
        # zebra and office cards in 209) gets no consumer negative, a business one in a consumer group (201) none
        for keyword, ad_group, owner_kind, _ in negatives:
            self.assertEqual(ad_group in B2B_AD_GROUPS, owner_kind == 'business', (keyword, ad_group))
        # the owner's campaign never takes its own search's negative: 902's campaign 108 (ad group 208) for zebra cards
        self.assertFalse([x for x in negatives if x[0] == 'zebra cards' and x[1] == '208'])
        # the rows' fields, in the order the loops wrote them (plan.json is written as they are)
        consumer = next(x for x in T.by_type(out, 'Negative exact') if not x.get('owner_kind'))
        business_row = next(x for x in T.by_type(out, 'Negative exact') if x.get('owner_kind'))
        head = ['step', 'type', 'keyword', 'campaign', 'ad_group', 'clicks90', 'orders90', 'spend90', 'campaign_id',
                'ad_group_id']
        self.assertEqual(list(consumer)[:13], head + ['why', 'how', 'product'])
        self.assertEqual(list(business_row)[:14], head + ['owner_kind', 'why', 'how', 'product'])
        self.assertEqual([list(x) for x in out['skipped_negatives']],
                         [['keyword', 'campaign', 'ad_group_id', 'why']] * 2
                         + [['keyword', 'campaign', 'ad_group_id', 'owner_kind', 'why']] * 2)
        # one loop writes both kinds' rows
        self.assertTrue(callable(getattr(planner, 'funnel_negatives', None)))

    def test_evidence_text_both_kinds(self):                                # Review Focus 5
        out = self.plan()
        # the rows carry today's two texts
        self.assertEqual(T.one(out, 'New exact campaign', keyword='zebra cards')['evidence'], ZEBRA_EVIDENCE)
        self.assertEqual(T.one(out, 'Business invest', keyword='zebra cards')['evidence'], ZEBRA_BUSINESS_EVIDENCE)
        # one text, chosen by the record's owner_kind
        consumer = next(r for r in out['terms'] if r['term'] == 'zebra cards')
        business_record = next(r for r in out['business_terms'] if r['term'] == 'zebra cards')
        self.assertEqual(planner.evidence_text(consumer), ZEBRA_EVIDENCE)
        self.assertEqual(planner.evidence_text(business_record), ZEBRA_BUSINESS_EVIDENCE)
        self.assertEqual((planner.evidence_text(None), planner.evidence_text({})), ('', ''))


if __name__ == '__main__':
    unittest.main()
