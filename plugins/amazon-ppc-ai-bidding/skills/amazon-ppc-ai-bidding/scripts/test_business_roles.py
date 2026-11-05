"""B2B keywords as full citizens of the planner: business search records built from the B2B campaigns' own
search-term rows, the pool's prior from config, and the business suggested-bid pull
(docs/superpowers/specs/2026-10-21-b2b-lane-and-roles-design.md, sections 4a and 4h).

The fixture below is shared by every task of the B2B lane-and-roles plan
(docs/superpowers/plans/2026-10-21-b2b-lane-and-roles.md). With its numbers and the pinned prior of 0.30, the pool is
(10 + 3.0) / (81 + 10); 'zebra cards' is a business Invest (25 B2B clicks, 7 orders, index about 2.4; owner 902, copy
905); 'blank cards' is a business Hold (40 clicks, 3 orders, index about 0.9); 'gold cards' is a business Test (12
clicks, 0 orders); 'office cards' is a business Invest with no B2B exact keyword; 'bulk thank you cards' has no SQP row.
"""
import contextlib
import io
import json
import os
import unittest

import human_review  # noqa: F401  (the later tasks' tests use it)
import lanes  # noqa: F401
import plan as planner
import plan_lanes  # noqa: F401
import test_business as B
import test_plan_lanes as T

B2B_STWS_EXACT = f'Cards - {T.ASIN} - B2B - Search Terms with Sales - Exact - 1'
B2B_EXACT2 = f'Cards - {T.ASIN} - B2B Launch Targets - Exact - 2'
T.IDS[B2B_STWS_EXACT] = ('110', '210'); T.IDS[B2B_EXACT2] = ('111', '211')
QUERIES = T.QUERIES + [T.query('zebra cards', 600, 240, 24, 20, 5), T.query('office cards', 800, 320, 32, 20, 5)]
SEARCH_TERMS = T.SEARCH_TERMS + [T.search_term('blank cards', B.B2B_EXACT, 40, 3, 30), T.search_term('zebra cards', B.B2B_EXACT, 20, 6, 24),
                                 T.search_term('zebra cards', B.B2B_STWS, 5, 1, 4), T.search_term('office cards', B.B2B_STWS, 15, 5, 12),
                                 T.search_term('gold cards', B.B2B_EXACT, 12, 0, 9)]
KEYWORDS = T.KEYWORDS + [T.keyword('901', 'blank cards', 'exact', B.B2B_EXACT, 1.05, 40, 3, 30),
                         T.keyword('902', 'zebra cards', 'exact', B.B2B_EXACT, 1.05, 20, 6, 24),
                         T.keyword('903', 'bulk thank you cards', 'phrase', B.B2B_STWS, 1.30, 2, 0, 1.0),
                         T.keyword('905', 'zebra cards', 'exact', B2B_EXACT2, 1.05, 4, 1, 3),
                         T.keyword('906', 'thank you notes', 'exact', B2B_STWS_EXACT, 0.80, 3, 0, 2),
                         T.keyword('907', 'gold cards', 'exact', B.B2B_EXACT, 1.00, 12, 0, 9)]
SUGGESTED = dict(T.SUGGESTED, **{'zebra cards': [0.40, 0.60, 0.80], 'office cards': [0.50, 0.70, 1.00]})
SUGGESTED_B = {'zebra cards': [0.60, 0.90, 1.20], 'office cards': [0.50, 0.80, 1.20]}
CAMPAIGNS = [dict(T.campaign(n), siteRestrictions=['AMAZON_BUSINESS']) for n in (B.B2B_EXACT, B.B2B_STWS, B2B_STWS_EXACT, B2B_EXACT2)]
BUSINESS = dict(pool_prior_cvr=0.30, pool_prior_as_of='2026-10-21', exact_campaign_marker='B2B - Search Terms with Sales - Exact',
                new_keyword_spend_share=0.25)


def shared():
    """The shared config the fixture plans on: the lanes fixture's, with the pool's prior pinned at 0.30 (never the live
    number, so a monthly refresh of config.json does not move these tests), and the standing rank top-of-search policy on,
    as it is live (Kim, 2026-10-20): a business invest sets its campaign's top of search to it (design 4b)."""
    s = T.shared_config(standing=True)
    s['business'] = dict(BUSINESS)
    return s


def product(**over):
    """The test product at a $10 price: $5 profit a unit, so a breakeven ACOS of 50% (budget_headroom.product_breakeven)."""
    return T.product(price=10.0, **over)


class BusinessRolesTest(unittest.TestCase):
    setUp = T.PlannerLanesTest.setUp
    shared = staticmethod(shared)

    def plan(self, cfg=None, shared=None, suggested_b=SUGGESTED_B, **over):
        """Plan the fixture. over changes make_run's arguments (keywords, search_terms, ... replace the fixture's); its
        extra files are added to the business suggested bids. suggested_b=None leaves suggested_bids_business.json out."""
        extra = {} if suggested_b is None else {'suggested_bids_business.json': suggested_b}
        extra.update(over.pop('extra', {}))
        run = dict(queries=QUERIES, search_terms=SEARCH_TERMS, keywords=KEYWORDS, more_campaigns=CAMPAIGNS, suggested=SUGGESTED)
        run.update(over)
        T.make_run(self.run_dir, extra=extra, **run)
        return planner.build(T.ASIN, cfg or product(), shared or self.shared(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)

    # --- Task 1: business evidence ------------------------------------------------------------------------------
    def test_pool_leans_on_the_config_prior(self):
        out = self.plan()
        self.assertAlmostEqual(out['summary'][0]['business']['pooled_cvr'], round((10 + 10 * 0.30) / (81 + 10), 4), places=4)
        self.assertEqual(out['summary'][0]['business']['pool_prior']['source'], 'config')

    def test_pool_falls_back_to_the_product_ad_conversion_without_the_config_number(self):
        s = self.shared()
        del s['business']['pool_prior_cvr']
        business = self.plan(shared=s)['summary'][0]['business']
        self.assertEqual(business['pool_prior'], dict(cvr=round(13 / 88, 4), as_of=T.TODAY, source='product ad conversion'))
        self.assertAlmostEqual(business['pooled_cvr'], round((10 + 10 * 13 / 88) / (81 + 10), 4), places=4)

    def test_business_record_runs_the_consumer_ladder_on_business_rows(self):
        bt = {r['term']: r for r in self.plan()['business_terms']}
        z = bt['zebra cards']
        self.assertEqual((z['role'], z['sub_role'], z['ad_clicks'], z['ad_orders'], z['owner_kind']), ('Rank', 'Invest', 25, 7, 'business'))
        self.assertGreater(z['index'], 1.1)
        self.assertEqual(bt['blank cards']['role'], 'Hold')
        self.assertEqual(bt['gold cards']['role'], 'Test')
        self.assertIsNone(bt['bulk thank you cards']['index'])

    def test_consumer_aggregates_drop_business_rows(self):
        out = self.plan()
        self.assertAlmostEqual(out['summary'][0]['asin_ad_cvr'], round(13 / 88, 4), places=4)   # T.SEARCH_TERMS only
        t = {r['term']: r for r in out['terms']}
        self.assertEqual(t['zebra cards']['ad_clicks'], 0)

    def test_organic_counts_both_kinds_ad_orders(self):                  # ruling 5: the stop-loss baseline is unchanged
        # 'zebra cards' with 12 SQP purchases, 2 consumer ad orders and 7 B2B ad orders: organic is what SQP's purchases
        # leave after every ad order of the search, as before the split (a B2B order is an order of the same ASIN)
        queries = [q for q in QUERIES if q['Query'] != 'zebra cards'] + [T.query('zebra cards', 600, 240, 24, 20, 12)]
        search_terms = SEARCH_TERMS + [T.search_term('zebra cards', T.STW, 6, 2, 3)]
        out = self.plan(queries=queries, search_terms=search_terms)
        organic = 12 - sum(m['Orders'] for m in search_terms if m['SearchTerm'] == 'zebra cards')
        self.assertEqual(organic, 3)
        consumer = next(r for r in out['terms'] if r['term'] == 'zebra cards')
        business = next(r for r in out['business_terms'] if r['term'] == 'zebra cards')
        self.assertEqual((consumer['organic_purchases'], consumer['organic_share']), (organic, organic / 12))
        self.assertEqual((business['organic_purchases'], business['organic_share']), (organic, organic / 12))

    def test_a_seasonal_product_invests_in_no_business_search(self):     # ruling 4
        # in harvest nothing is invested in: 'zebra cards' would be a business Invest, so it bids as Defend, and the run
        # never stops for a business bid pull (no suggested_bids_business.json at all)
        out = self.plan(cfg=product(mode='harvest'), suggested_b=None)
        self.assertEqual(out['summary'][0]['season']['phase'], 'harvest')
        bt = {r['term']: r for r in out['business_terms']}
        self.assertEqual((bt['zebra cards']['role'], bt['zebra cards']['sub_role'], bt['zebra cards'].get('season_defend')),
                         ('Defend', 'Defend', True))
        self.assertFalse([r for r in out['business_terms'] if r['role'] == 'Rank'])
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'need_suggested_bids_business.json')))

    def test_missing_business_suggestion_stops_the_run(self):            # Review Focus 5
        printed = io.StringIO()
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(printed):
            self.plan(suggested_b={'office cards': [0.50, 0.80, 1.20]})
        self.assertEqual(cm.exception.code, 2)
        self.assertIn('need_suggested_bids_business.json', printed.getvalue())
        with open(os.path.join(self.run_dir, 'need_suggested_bids_business.json'), encoding='utf-8') as fh:
            need = json.load(fh)
        self.assertEqual([s['search'] for s in need['searches']], ['zebra cards'])
        self.assertEqual(need['searches'][0]['ad_group_id'], '208')
        # an entry can carry no ids (no B2B row named one): the how says where to read it then, as the consumer file does
        self.assertIn('in the named B2B ad group, or any enabled B2B ad group of the product when none is named', need['how'])

    # --- Task 2: business roles, the Business invest promotion, one owner inside the kind ------------------------------
    def test_owner_keyword_becomes_a_business_invest_bounded_at_the_business_high(self):
        out = self.plan()
        row = T.one(out, 'Business invest', keyword='zebra cards')
        self.assertEqual((row['keyword_id'], row['campaign_id'], row['role'], row['tos'], row['budget'], row['owner_kind']), ('902', '108', 'Invest', 50, 10, 'business'))
        self.assertEqual(row['new'], 1.20)                     # be_b about 1.4 > the business high 1.20
        self.assertFalse([x for x in T.by_type(out, 'Bid change') if x.get('keyword_id') == '902'])
        plan_row = next(p for p in out['keyword_plan'] if p['keyword_id'] == '902')
        self.assertTrue(plan_row['action'].startswith('Invest'))

    def test_business_copy_is_paused_and_the_b2b_phrase_group_gets_the_negative(self):   # Review Focus 2 (rows)
        out = self.plan()
        pause = T.one(out, 'Pause keyword', keyword_id='905')
        self.assertEqual((pause['owner_kind'], 'business owner' in pause['why']), ('business', True))
        neg = T.one(out, 'Negative exact', keyword='zebra cards', ad_group_id='209')
        self.assertEqual(neg['owner_kind'], 'business')
        self.assertFalse([x for x in T.by_type(out, 'Negative exact') if x['keyword'] == 'zebra cards' and x['ad_group_id'] == '211'])
        self.assertFalse([x for x in T.by_type(out, 'Negative exact') if x['keyword'] == 'zebra cards' and x.get('owner_kind') != 'business'])

    def test_consumer_and_business_both_invest_in_the_same_search(self):
        out = self.plan()
        T.one(out, 'New exact campaign', keyword='zebra cards')    # the consumer owner, created
        T.one(out, 'Business invest', keyword='zebra cards')

    def test_invest_search_without_a_b2b_exact_keyword_gets_a_new_exact_keyword(self):   # Review Focus 1
        out = self.plan()
        row = T.one(out, 'New exact keyword', keyword='office cards')
        self.assertEqual((row['campaign_id'], row['ad_group_id'], row['owner_kind'], row['role']), ('110', '210', 'business', 'Invest'))
        self.assertFalse([x for x in T.by_type(out, 'Business invest') if x['keyword'] == 'office cards'])
        self.assertIn('negatives', row['how'])

    def test_two_invests_in_one_campaign_write_one_campaign_update(self):   # Review Focus 3
        kws = KEYWORDS + [T.keyword('908', 'office cards', 'exact', B.B2B_EXACT, 1.00, 16, 4, 14)]
        sts = SEARCH_TERMS + [T.search_term('office cards', B.B2B_EXACT, 16, 4, 14)]
        out = self.plan(keywords=kws, search_terms=sts)
        rows = [x for x in T.by_type(out, 'Business invest') if x['campaign_id'] == '108']
        self.assertEqual(sorted(x['keyword'] for x in rows), ['office cards', 'zebra cards'])
        files = dict(planner.payload_entries(rows, self.shared(), T.ASIN))
        camps = [e for _, e in files['5_campaign_updates.json'] if str(e.get('campaignId')) == '108']
        self.assertEqual(len(camps), 1)
        self.assertEqual([p['percentage'] for p in camps[0]['dynamicBidding']['placementBidding'] if p['placement'] == 'PLACEMENT_TOP'], [50])
        self.assertEqual(len(files['2b_business_invest_specs.json']), 2)

    def test_business_hold_row_keeps_phase_one_pricing(self):
        row = T.one(self.plan(), 'Bid change', keyword_id='901')
        self.assertEqual((row['role'], row['owner_kind']), ('Hold', 'business'))

    def test_owner_ad_groups_are_on_the_checks_list(self):
        out = self.plan()
        self.assertIn(dict(keyword='zebra cards', campaign_id='108', ad_group_id='208'), out['checks'])

    # --- Task 2: the rest of the interface ------------------------------------------------------------------------------
    def test_summary_counts_the_business_invests(self):
        # zebra cards: one Invest (902), its copy 905 paused, a negative in the phrase group 209; office cards: a new exact
        # keyword, its phrase group 209 negated too (the owner's campaign is 110 from now on)
        business = self.plan()['summary'][0]['business']
        self.assertEqual({k: business[k] for k in ('invest', 'prove_first', 'copies_paused', 'negatives', 'new_keywords')},
                         dict(invest=1, prove_first=0, copies_paused=1, negatives=2, new_keywords=1))

    def test_new_exact_keyword_payload_and_its_campaign_update(self):
        out = self.plan()
        files = dict(planner.payload_entries(out['changes'], self.shared(), T.ASIN))
        self.assertEqual([e for _, e in files['1c_new_keywords.json']],
                         [dict(type='sp_keywords', campaignId='110', adGroupId='210', keywordText='office cards', matchType='EXACT',
                               bid=1.20, state='ENABLED')])
        self.assertEqual([e['budget']['budget'] for _, e in files['5_campaign_updates.json'] if e['campaignId'] == '110'], [10])
        self.assertIn(dict(keyword='office cards', campaign_id='110', ad_group_id='210'), out['checks'])

    def test_held_placements_write_the_budget_only(self):
        # the standing policy off (or a campaign it can't be written to safely): the B2B campaign keeps its live top of
        # search, as a reused consumer campaign does, and the negatives check stays in the row's how
        s = self.shared()
        s['placement']['rank_tos_standing']['approved'] = False
        out = self.plan(shared=s)
        row = T.one(out, 'Business invest', keyword='zebra cards')
        self.assertEqual((row['placement_hold'], row['tos'], row['tos_now']), (True, 0, 0))
        self.assertIn('negatives', row['how'])
        self.assertIn('negatives', T.one(out, 'New exact keyword', keyword='office cards')['how'])
        files = dict(planner.payload_entries([row], s, T.ASIN))
        self.assertEqual([e for _, e in files['5_campaign_updates.json']],
                         [dict(type='sp_campaigns', campaignId='108', budget=dict(budget=10, budgetType='DAILY'))])

    def test_owner_is_the_most_clicked_b2b_exact_keyword_ties_to_the_lower_campaign(self):
        for clicks, owner, copy in ((20, '902', '909'), (21, '909', '902')):
            with self.subTest(clicks=clicks):
                kws = KEYWORDS + [T.keyword('909', 'zebra cards', 'exact', B2B_STWS_EXACT, 1.05, clicks, 6, 24)]
                out = self.plan(keywords=kws)
                self.assertEqual(T.one(out, 'Business invest', keyword='zebra cards')['keyword_id'], owner)
                self.assertTrue(T.one(out, 'Pause keyword', keyword_id=copy)['why'].startswith('Amazon Business campaign'))
                self.assertFalse([x for x in T.by_type(out, 'Bid change') if x.get('keyword_id') in ('902', '909')])

    def test_an_owner_already_invested_as_planned_writes_no_row(self):
        # 902 already at its invest bid, its campaign at the policy's +50% and the invest budget: nothing to change, so no
        # Business invest row; its copy still pauses and its funnel negative still goes out
        kws = [k for k in KEYWORDS if k['KeywordId'] != '902'] + [T.keyword('902', 'zebra cards', 'exact', B.B2B_EXACT, 1.20, 20, 6, 24)]
        camps = [c for c in CAMPAIGNS if c['name'] != B.B2B_EXACT] + [dict(T.campaign(B.B2B_EXACT, tos=50), siteRestrictions=['AMAZON_BUSINESS'])]
        out = self.plan(keywords=kws, more_campaigns=camps)
        self.assertFalse(T.by_type(out, 'Business invest'))
        T.one(out, 'Pause keyword', keyword_id='905')
        T.one(out, 'Negative exact', keyword='zebra cards', ad_group_id='209')

    def test_a_b2b_exact_campaign_never_takes_the_funnel_negative(self):
        out = self.plan(search_terms=SEARCH_TERMS + [T.search_term('zebra cards', B2B_EXACT2, 4, 1, 3)])
        self.assertFalse([x for x in T.by_type(out, 'Negative exact') if x['ad_group_id'] == '211'])
        skipped = [x for x in out['skipped_negatives'] if x['keyword'] == 'zebra cards' and x['ad_group_id'] == '211']
        self.assertEqual([(x['owner_kind'], 'B2B exact campaign' in x['why']) for x in skipped], [('business', True)])

    def test_a_new_keyword_whose_ad_group_is_unknown_says_so_and_writes_nothing(self):
        # no keyword row of the B2B exact campaign 110 was read (906 dropped), so the ad group the keyword goes into is not
        # known: the row says to list it first, carries no payload, and the phrase group keeps the search's traffic. The
        # placement hold (the standing policy off) leaves its how as the planner wrote it
        for standing in (True, False):
            with self.subTest(standing=standing):
                s = self.shared()
                s['placement']['rank_tos_standing']['approved'] = standing
                out = self.plan(shared=s, keywords=[k for k in KEYWORDS if k['KeywordId'] != '906'])
                row = T.one(out, 'New exact keyword', keyword='office cards')
                self.assertEqual((row['campaign_id'], row['ad_group_id']), ('110', None))
                self.assertIn('sp_ad_groups', row['how'])
                self.assertIn('negatives', row['how'])
                files = dict(planner.payload_entries(out['changes'], s, T.ASIN))
                self.assertNotIn('1c_new_keywords.json', files)
                self.assertFalse([e for _, e in files.get('5_campaign_updates.json', []) if e['campaignId'] == '110'])
                self.assertFalse([x for x in T.by_type(out, 'Negative exact') if x['keyword'] == 'office cards'])

    # --- Task 2, fix round 1 ---------------------------------------------------------------------------------------------
    def test_a_keyword_in_an_archived_campaign_is_never_the_owner(self):          # finding 1
        # 909 has the most clicks, but its campaign (110) is archived: the enabled 902 owns the search, nothing is written
        # to 110, and 902 is never paused as a copy
        kws = KEYWORDS + [T.keyword('909', 'zebra cards', 'exact', B2B_STWS_EXACT, 1.05, 25, 6, 24)]
        camps = [c for c in CAMPAIGNS if c['name'] != B2B_STWS_EXACT] + [dict(T.campaign(B2B_STWS_EXACT), state='ARCHIVED',
                                                                              siteRestrictions=['AMAZON_BUSINESS'])]
        out = self.plan(keywords=kws, more_campaigns=camps)
        row = T.one(out, 'Business invest', keyword='zebra cards')
        self.assertEqual((row['keyword_id'], row['campaign_id']), ('902', '108'))
        self.assertFalse([x for x in T.by_type(out, 'Pause keyword') if x.get('keyword_id') == '902'])
        T.one(out, 'Pause keyword', keyword_id='905')
        files = dict(planner.payload_entries(out['changes'], self.shared(), T.ASIN))
        self.assertFalse([e for _, e in files['5_campaign_updates.json'] if e['campaignId'] == '110'])

    def test_no_owner_that_can_invest_means_no_invest_and_no_copy_paused(self):   # finding 1
        # the only enabled candidate, 902, is held by the live inventory (its target is not enabled) and 905's campaign is
        # paused: no Business invest, no copy paused (905 keeps its phase 1 price), no new keyword for a search that has
        # one, and no business bid pull asked for it
        inventory = dict(asin=T.ASIN, keyword_id='902', ad_product='SP', match='exact', campaign_id='108', ad_group_id='208',
                         keyword='zebra cards', observed_on=T.TODAY, current_bid=1.05,
                         gates=dict(campaign_enabled=True, ad_group_enabled=True, target_enabled=False))
        camps = [c for c in CAMPAIGNS if c['name'] != B2B_EXACT2] + [dict(T.campaign(B2B_EXACT2), state='PAUSED',
                                                                          siteRestrictions=['AMAZON_BUSINESS'])]
        out = self.plan(more_campaigns=camps, suggested_b={'office cards': [0.50, 0.80, 1.20]},
                        extra={'visibility_inputs.json': dict(asin=T.ASIN, inventory_complete=True, inventory=[inventory],
                                                              delivery=[], recommendations=[], experiments=[])})
        self.assertFalse([x for x in out['changes'] if x['type'] in ('Business invest', 'New exact keyword')
                          and x['keyword'] == 'zebra cards'])
        self.assertFalse([x for x in T.by_type(out, 'Pause keyword') if x.get('keyword_id') in ('902', '905')])
        plan_rows = {p['keyword_id']: p for p in out['keyword_plan']}
        self.assertTrue(plan_rows['902']['action'].startswith('Keep'))
        self.assertTrue(plan_rows['905']['action'].startswith('Hold at breakeven (business'))
        self.assertFalse([x for x in T.by_type(out, 'Negative exact') if x['keyword'] == 'zebra cards'])

    def test_copies_pause_only_while_the_owner_invests(self):                     # finding 1
        # the owner 902 is enabled, but the visibility review keeps its bid: it doesn't invest this run, so its copy 905 keeps
        # its phase 1 price and the search keeps its B2B exact coverage
        # a check that came back "no" (a negative in the way) holds the owner: since decision 107 (2026-10-23) a check that
        # couldn't be answered (its live strategy unread) holds nothing
        inventory = dict(asin=T.ASIN, keyword_id='902', ad_product='SP', match='exact', campaign_id='108', ad_group_id='208',
                         keyword='zebra cards', observed_on=T.TODAY, current_bid=1.05, strategy='LEGACY_FOR_SALES',
                         gates=dict(campaign_enabled=True, ad_group_enabled=True, target_enabled=True, negatives_clear=False))
        out = self.plan(extra={'visibility_inputs.json': dict(asin=T.ASIN, inventory_complete=True, inventory=[inventory],
                                                              delivery=[], recommendations=[], experiments=[])})
        plan_rows = {p['keyword_id']: p for p in out['keyword_plan']}
        self.assertTrue(plan_rows['902']['action'].startswith('Keep pending visibility review'))
        self.assertEqual((plan_rows['905']['role'], plan_rows['905']['action'][:17]), ('Hold', 'Hold at breakeven'))
        self.assertFalse(T.by_type(out, 'Business invest'))
        self.assertFalse([x for x in T.by_type(out, 'Pause keyword') if x.get('keyword_id') == '905'])
        self.assertNotIn(dict(keyword='zebra cards', campaign_id='108', ad_group_id='208'), out['checks'])

    def test_a_campaign_s_business_invests_share_one_top_of_search_and_budget(self):   # finding 2 (ruling 6)
        # office cards (908, 2 B2B orders) is a Prove first beside zebra cards' Invest in campaign 108: both rows carry the
        # campaign-wide +50% and $10, so the Prove first row approved on its own still writes +50% for 108
        kws = KEYWORDS + [T.keyword('908', 'office cards', 'exact', B.B2B_EXACT, 1.00, 16, 2, 14)]
        sts = [s for s in SEARCH_TERMS if s['SearchTerm'] != 'office cards'] + [T.search_term('office cards', B.B2B_EXACT, 16, 2, 14)]
        out = self.plan(keywords=kws, search_terms=sts)
        rows = {x['keyword']: x for x in T.by_type(out, 'Business invest') if x['campaign_id'] == '108'}
        self.assertEqual({k: (x['role'], x['tos'], x['campaign_tos'], x['campaign_budget']) for k, x in rows.items()},
                         {'zebra cards': ('Invest', 50, 50, 10), 'office cards': ('Prove first', 30, 50, 10)})
        files = dict(planner.payload_entries([rows['office cards']], self.shared(), T.ASIN))
        [update] = [e for _, e in files['5_campaign_updates.json'] if e['campaignId'] == '108']
        self.assertEqual([p['percentage'] for p in update['dynamicBidding']['placementBidding'] if p['placement'] == 'PLACEMENT_TOP'], [50])
        self.assertEqual(update['budget'], dict(budget=10, budgetType='DAILY'))
        self.assertEqual(files['2b_business_invest_specs.json'][0][1]['tos'], 50)
        self.assertIn('+50%', rows['office cards']['why'])
        self.assertIn('zebra cards Invest, office cards Prove first', rows['office cards']['why'])

    def test_an_invest_already_live_keeps_its_campaign_top_of_search(self):        # finding 4
        # 902 is already at its invest bid in campaign 108, which runs the policy's +50% and $10: it writes no row. A new
        # Prove first (908, office cards) in the same campaign must not take 108 down to +30% under it
        kws = [k for k in KEYWORDS if k['KeywordId'] != '902'] + [
            T.keyword('902', 'zebra cards', 'exact', B.B2B_EXACT, 1.20, 20, 6, 24),
            T.keyword('908', 'office cards', 'exact', B.B2B_EXACT, 1.00, 16, 2, 14)]
        sts = [s for s in SEARCH_TERMS if s['SearchTerm'] != 'office cards'] + [T.search_term('office cards', B.B2B_EXACT, 16, 2, 14)]
        camps = [c for c in CAMPAIGNS if c['name'] != B.B2B_EXACT] + [dict(T.campaign(B.B2B_EXACT, tos=50), siteRestrictions=['AMAZON_BUSINESS'])]
        out = self.plan(keywords=kws, search_terms=sts, more_campaigns=camps)
        self.assertFalse([x for x in T.by_type(out, 'Business invest') if x['keyword'] == 'zebra cards'])
        row = T.one(out, 'Business invest', keyword='office cards')
        self.assertEqual((row['role'], row['tos'], row['tos_now'], row['campaign_tos'], row['campaign_budget']),
                         ('Prove first', 30, 50, 50, 10))
        self.assertIn('zebra cards Invest (already live), office cards Prove first', row['why'])
        files = dict(planner.payload_entries(out['changes'], self.shared(), T.ASIN))
        [update] = [e for _, e in files['5_campaign_updates.json'] if e['campaignId'] == '108']
        self.assertEqual([p['percentage'] for p in update['dynamicBidding']['placementBidding'] if p['placement'] == 'PLACEMENT_TOP'], [50])
        self.assertEqual(files['2b_business_invest_specs.json'][0][1]['tos'], 50)

    def test_a_campaign_not_read_live_gets_no_budget(self):                       # finding 3 (ruling 7)
        # campaign 108 is missing from campaigns.json: the row keeps the planner's floor ($10) with budget_now None, and no
        # budget is written (it could lower the team's budget); the how says to check it first
        camps = [c for c in CAMPAIGNS if c['name'] != B.B2B_EXACT]
        s = self.shared()
        s['placement']['recommendations']['enabled'] = False   # no placement review: the policy is written as planned
        out = self.plan(shared=s, more_campaigns=camps)
        row = T.one(out, 'Business invest', keyword='zebra cards')
        self.assertEqual((row['budget'], row['budget_now'], row['campaign_budget']), (10, None, None))
        self.assertIn('not read live', row['how'])
        files = dict(planner.payload_entries([row], s, T.ASIN))
        [update] = [e for _, e in files['5_campaign_updates.json'] if e['campaignId'] == '108']
        self.assertNotIn('budget', update)
        self.assertIn('dynamicBidding', update)
        self.assertIsNone(files['2b_business_invest_specs.json'][0][1]['budget'])
        # with the placement review on, a campaign not read live is held too: nothing at all is written to it
        out = self.plan(more_campaigns=camps)
        row = T.one(out, 'Business invest', keyword='zebra cards')
        self.assertIn('not read live', row['how'])
        files = dict(planner.payload_entries([row], self.shared(), T.ASIN))
        self.assertFalse([e for _, e in files.get('5_campaign_updates.json', []) if e['campaignId'] == '108'])

    def test_missing_suggestion_for_a_new_keyword_names_its_b2b_exact_ad_group(self):
        printed = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(printed):
            self.plan(suggested_b={'zebra cards': [0.60, 0.90, 1.20]})
        with open(os.path.join(self.run_dir, 'need_suggested_bids_business.json'), encoding='utf-8') as fh:
            need = json.load(fh)
        self.assertEqual(need['searches'], [dict(search='office cards', campaign_id='110', ad_group_id='210')])

    # --- Task 3: the lanes read business evidence; locks, invested and forecasts per kind --------------------------------
    def test_business_rows_take_the_normal_lanes(self):
        out = self.plan()
        rows = [x for x in out['changes'] if x.get('owner_kind') == 'business']
        self.assertTrue(rows)
        self.assertFalse([x for x in rows if 'business lane' in x['lane_reason']])
        cut = T.one(out, 'Bid change', keyword_id='907')          # gold cards: a business cut
        self.assertEqual(cut['lane'], 'auto')
        inv = T.one(out, 'Business invest', keyword='zebra cards')
        self.assertIsNotNone(inv['modelled_spend_month'])
        self.assertIn(inv['lane'], ('auto', 'human'))
        # a business promotion is the book owner's whatever it spends (Lee's until 2026-10-22; no money level since
        # decision 99)
        self.assertNotIn('past_kim_level', inv)
        self.assertEqual(human_review.row_levels(out)[out['changes'].index(inv)], 'owner')
        # ruling 11: the new keyword's modelled orders are capped at what office cards earned a month across the B2B
        # campaigns (5 orders in 90 days / 3), never its B2B orders per dollar on the full $75 (31 orders)
        new = next(r for r in out['rerank'] if r.get('owner_kind') == 'business' and r['keyword'] == 'office cards')
        self.assertEqual((new['spend'], new['orders'], new['net']), (75, round(5 / 3, 1), round(5 / 3 * 5 - 75)))

    def test_a_b2b_campaign_above_the_standard_budget_is_not_odd(self):          # ruling 9
        # campaign 108 runs $20 a day live: the zebra cards Invest keeps it (a budget is never lowered), and that is its
        # standard budget, so the proven invest stays automatic
        camps = [c for c in CAMPAIGNS if c['name'] != B.B2B_EXACT] + [dict(T.campaign(B.B2B_EXACT, budget=20),
                                                                          siteRestrictions=['AMAZON_BUSINESS'])]
        row = T.one(self.plan(more_campaigns=camps), 'Business invest', keyword='zebra cards')
        self.assertEqual((row['budget'], row['budget_now'], row['lane']), (20, 20, 'auto'), row['lane_reason'])

    def test_bundles_do_not_cross_kinds(self):                      # Review Focus 2 (lanes)
        # a consumer search-term row for zebra cards gives the consumer promotion a bundle of its own (a funnel negative in
        # the consumer group 201); without one it has no bundle to check
        out = self.plan(search_terms=SEARCH_TERMS + [T.search_term('zebra cards', T.STW, 6, 2, 3)])
        members, _ = plan_lanes.bundles(out['changes'])
        heads = {out['changes'][i]['type']: m for i, m in members.items() if out['changes'][i]['keyword'] == 'zebra cards'}
        self.assertEqual({x.get('keyword_id') or x.get('ad_group_id') for x in heads['Business invest']}, {'905', '209'})
        self.assertTrue(heads['New exact campaign'])
        self.assertFalse([x for x in heads['New exact campaign'] if x.get('owner_kind') == 'business'])

    def test_a_consumer_decision_no_longer_holds_the_business_row(self):   # Review Focus 4
        # a decline with no direction holds every move (lanes.lock_blocks), as a hand-written decline does; its reason
        # names the decliner (plan_lanes.decision_lock: "decided by Lee on ...")
        decided = [dict(id='zebra cards', what='decline', by='Lee', until='2026-11-30', on='2026-10-12')]
        out = self.plan(cfg=product(decisions=decided))
        self.assertIn('decided by Lee', T.one(out, 'New exact campaign', keyword='zebra cards')['lane_reason'])
        self.assertNotIn('decided by Lee', T.one(out, 'Business invest', keyword='zebra cards')['lane_reason'])
        out = self.plan(cfg=product(decisions=[dict(decided[0], owner_kind='business')]))
        self.assertIn('decided by Lee', T.one(out, 'Business invest', keyword='zebra cards')['lane_reason'])
        self.assertNotIn('decided by Lee', T.one(out, 'New exact campaign', keyword='zebra cards')['lane_reason'])

    def test_invested_is_per_kind(self):
        log = {'gold cards': dict(since='2026-09-20', role='Invest')}
        self.assertEqual(T.one(self.plan(cfg=product(invest_log=log)), 'Bid change', keyword_id='907')['lane'], 'auto')
        out = self.plan(cfg=product(business_invest_log=log))
        row = T.one(out, 'Bid change', keyword_id='907')
        # flagged per kind; since autonomous runs (2026-10-22) the cut applies on its own like any cut
        self.assertEqual((row['lane'], row.get('invested_search')), ('auto', True))

    def test_a_campaign_s_business_invests_go_out_as_one_group(self):     # ruling 6 (lanes)
        # zebra cards (Invest) and office cards (Prove first) in campaign 108 write one campaign update: one lane for both;
        # the head (the higher opportunity) carries the group's monthly spend and the Prove first row rides it as a member
        # office cards: 18 clicks since 2026-10-22 (was 16, index 1.31 under the old 1.4 bar): 2 B2B orders at index 1.21,
        # under the 1.25 Prove first needs now (data-stage design 4.4), so it is held (a person's call until decision 107)
        kws = KEYWORDS + [T.keyword('908', 'office cards', 'exact', B.B2B_EXACT, 1.00, 18, 2, 14)]
        sts = [s for s in SEARCH_TERMS if s['SearchTerm'] != 'office cards'] + [T.search_term('office cards', B.B2B_EXACT, 18, 2, 14)]
        out = self.plan(keywords=kws, search_terms=sts)
        rows = {x['keyword']: x for x in T.by_type(out, 'Business invest') if x['campaign_id'] == '108'}
        head, member = rows['zebra cards'], rows['office cards']
        self.assertEqual((head['role'], member['role']), ('Invest', 'Prove first'))
        self.assertEqual(head['lane'], member['lane'])
        # the weakest lane: zebra cards is proved on its own, but office cards (2 B2B orders at index 1.21, under the 1.25
        # Prove first needs) is held, so the whole group is (decision 107)
        self.assertEqual(head['lane'], 'monitor')
        self.assertIn('office cards is held back', head['lane_reason'])
        self.assertTrue(member['lane_reason'].startswith(f'part of the business invests of {B.B2B_EXACT}'), member['lane_reason'])
        self.assertIn(head['lane_reason'], member['lane_reason'])
        self.assertEqual(head['group_spend_month'], head['modelled_spend_month'] + member['modelled_spend_month'])
        self.assertNotIn('group_spend_month', member)
        members, in_bundle = plan_lanes.bundles(out['changes'])
        self.assertIn(out['changes'].index(member), in_bundle)
        self.assertNotIn(out['changes'].index(head), in_bundle)
        self.assertIn(member, members[out['changes'].index(head)])

    # --- Task 4: placements, budget steps, the blacklist rescue and Scale Insights, the same as consumer ----------------
    def test_scale_insights_row_until_the_product_file_says_done(self):
        row = T.one(self.plan(), 'Scale Insights rules', owner_kind='business')
        self.assertIn(B.B2B_EXACT, row['new']); self.assertEqual(row['lane'], 'auto')  # the standard setup (2026-10-22)
        # done: the rules came off, and the campaigns holding a business invest (108, 110) are on 103 (ruling 17)
        done = dict(si_rules_off='2026-10-25', si_exact_owners=['108', '110'])
        self.assertFalse(T.by_type(self.plan(cfg=product(business=done)), 'Scale Insights rules'))

    def test_a_campaign_newly_holding_a_business_invest_is_moved_after_the_rules_came_off(self):   # I4, ruling 17
        # the rules came off (si_rules_off) with 108 moved to 103 (si_exact_owners); 110 newly holds office cards' new exact
        # keyword this run: the row names only 110 and office cards, and says to record 110 in si_exact_owners
        cfg = product(business=dict(si_rules_off='2026-10-25', si_exact_owners=['108']))
        row = T.one(self.plan(cfg=cfg), 'Scale Insights rules', owner_kind='business')
        self.assertTrue(row['new'].startswith(f'Strategy 103 / 302497 for the exact campaigns that newly own a business invest '
                                              f'search ({B2B_STWS_EXACT}), with those searches whitelisted (office cards)'), row['new'])
        for name in (B.B2B_EXACT, B.B2B_STWS, B2B_EXACT2):
            self.assertNotIn(name, row['new'])
        self.assertNotIn('zebra cards', row['new'])
        self.assertIn('add 110 to business.si_exact_owners', row['how'])
        self.assertEqual(row['lane'], 'auto')
        # ids are compared as text: a number in the product file counts too
        cfg = product(business=dict(si_rules_off='2026-10-25', si_exact_owners=[108, 110]))
        self.assertFalse(T.by_type(self.plan(cfg=cfg), 'Scale Insights rules'))

    def test_scale_insights_row_puts_the_owner_campaigns_on_103_and_the_rest_on_101(self):
        # 108 owns zebra cards (Business invest) and 110 takes the office cards New exact keyword: the exact-owners strategy,
        # their searches whitelisted. 109 (phrase) and 111 (zebra cards' paused copy) go to the keyword-ads strategy
        row = T.one(self.plan(), 'Scale Insights rules', owner_kind='business')
        owners, others = row['new'].split('; ')
        self.assertTrue(owners.startswith('Strategy 103 / 302497 '), owners)
        self.assertTrue(others.startswith('strategy 101 / 302489 '), others)
        for name in (B.B2B_EXACT, B2B_STWS_EXACT):
            self.assertIn(name, owners)
            self.assertNotIn(name, others)
        for name in (B.B2B_STWS, B2B_EXACT2):
            self.assertIn(name, others)
            self.assertNotIn(name, owners)
        self.assertIn('whitelisted (office cards, zebra cards)', owners)
        self.assertIn('business.si_rules_off', row['how'])
        self.assertIn('add 108, 110 to business.si_exact_owners', row['how'])
        # a product with no B2B campaign in the campaign read or the keyword report gets no row (ruling 18: a B2B campaign
        # the keyword report names counts, read live or not)
        out = self.plan(more_campaigns=[], keywords=T.KEYWORDS, search_terms=T.SEARCH_TERMS)
        self.assertFalse([x for x in T.by_type(out, 'Scale Insights rules') if x.get('owner_kind') == 'business'])
        out = self.plan(more_campaigns=[])
        self.assertTrue([x for x in T.by_type(out, 'Scale Insights rules') if x.get('owner_kind') == 'business'])

    def test_onboarding_keeps_the_business_row_apart_from_the_product_row(self):
        # both rows are 'Scale Insights rules' with no ad group: the business one carries its own row id, so a decision on
        # one never lands on the other, and it is the same id in the weekly run
        T.make_run(self.run_dir, extra={'suggested_bids_business.json': SUGGESTED_B}, queries=QUERIES, search_terms=SEARCH_TERMS,
                   keywords=KEYWORDS, more_campaigns=CAMPAIGNS, suggested=SUGGESTED)
        out = planner.build(T.ASIN, product(), self.shared(), self.run_dir, 'onboard', T.TODAY, now_utc=T.NOW)
        rows = T.by_type(out, 'Scale Insights rules')
        self.assertEqual(sorted(x.get('owner_kind') or 'consumer' for x in rows), ['business', 'consumer'])
        business = T.one(out, 'Scale Insights rules', owner_kind='business')
        self.assertEqual(len({x['row_id'] for x in rows}), 2)
        self.assertEqual(business['row_id'], T.one(self.plan(), 'Scale Insights rules', owner_kind='business')['row_id'])
        # a decline of the onboarding row never holds the business row; a decline of the business row holds it
        consumer = next(x for x in rows if x.get('owner_kind') != 'business')
        for declined, held in ((consumer['row_id'], False), (business['row_id'], True)):
            with self.subTest(declined=declined):
                decided = [dict(id=declined, what='decline', by='Lee', until='2026-11-30', on='2026-10-12')]
                row = T.one(self.plan(cfg=product(decisions=decided)), 'Scale Insights rules', owner_kind='business')
                self.assertEqual('decided by Lee' in row['lane_reason'], held, row['lane_reason'])

    def test_business_invest_log_searches_come_off_the_blacklist(self):
        # gold cards is a business Test this run but in the business invest log: the rescue takes its variant off
        cfg = product(business_invest_log={'gold cards': dict(since='2026-10-01', role='Invest')})
        lists = dict(NegativeExactList=['gold card', 'other'], NegativePhraseList=[], ExactWhiteList=[], _read='test')
        row = T.one(self.plan(cfg=cfg, extra={'si_blacklist.json': lists}), 'Scale Insights setup', step=95)
        self.assertEqual(row['exact_remove'], ['gold card'])
        self.assertIn('gold cards', row['whitelist_add'])

    # --- Task 5: the business invest log's stop-loss, on the B2B keyword's own orders and ACOS (design 4f) ---------------
    # Since autonomous runs (2026-10-22, decision 98) the planner writes the step-down itself (stop_loss.py): the owner
    # keyword (902, in campaign 108) back to its breakeven. The fixture's owner bids $1.05, under its B2B breakeven, so these
    # tests put it at $2.00 to have a bid to step down
    HIGH_OWNER = [k if k['KeywordId'] != '902' else dict(k, Bid=2.00) for k in KEYWORDS]

    def step_downs(self, out, search='zebra cards'):
        return [x for x in out['changes'] if x.get('stop_loss_step_down') and x.get('owner_kind') == 'business'
                and x['keyword'] == search]

    def test_business_stop_loss_judges_orders_and_acos(self):
        log = {'zebra cards': dict(since='2026-09-10', role='Invest', orders_then=7, clicks_then=20, owner_kind='business')}
        out = self.plan(cfg=product(business_invest_log=log), keywords=self.HIGH_OWNER)
        [row] = self.step_downs(out)
        self.assertEqual((row['type'], row['keyword_id'], row['role'], row['current'], row['lane']),
                         ('Bid change', '902', 'Hold', 2.0, 'auto'))
        self.assertLess(row['new'], row['current'])
        self.assertFalse(T.by_type(out, 'Stop-loss review'))  # no person's review: the run steps it down itself
        # the search's business invest row (it would invest again), its copies' pauses and its funnel negatives are dropped
        self.assertFalse([x for x in out['changes'] if x.get('owner_kind') == 'business' and x['keyword'] == 'zebra cards'
                          and x['type'] in ('Business invest', 'Negative exact', 'Pause keyword')])
        log['zebra cards']['orders_then'] = 3               # grown to 7; ACOS 28/70 = 40% <= 50%
        out = self.plan(cfg=product(business_invest_log=log), keywords=self.HIGH_OWNER)
        self.assertFalse(self.step_downs(out))
        self.assertTrue(T.by_type(out, 'Business invest'))

    def test_business_stop_loss_says_what_it_judged(self):
        # 39 days in, 7 B2B orders then and now, ACOS 28/70 = 40% under the 50% breakeven: one gain of the two
        log = {'zebra cards': dict(since='2026-09-10', role='Prove first', orders_then=7, clicks_then=20, owner_kind='business',
                                   campaign_id='108')}
        out = self.plan(cfg=product(business_invest_log=log), keywords=self.HIGH_OWNER)
        [row] = self.step_downs(out)
        self.assertEqual((row['campaign_id'], row['row_id']), ('108', 'Bid change:902'))
        self.assertEqual(row['stop_loss_reason'], 'invested in the B2B campaign for 39 days (5 weeks): B2B orders 7 -> 7, ACOS '
                                                  '40% against the 50% breakeven')
        self.assertEqual(row['lane_reason'], row['stop_loss_reason'])
        self.assertTrue(row['why'].startswith('Stop-loss step-down: invested in the B2B campaign for 39 days'), row['why'])
        [stop] = out['stop_loss']
        self.assertEqual((stop['keyword'], stop['owner_kind'], stop['age_days'], stop['gains'], stop['step_down']),
                         ('zebra cards', 'business', 39, ['ACOS at or under breakeven'], 'written'))
        # the fixture's own owner already bids under its breakeven, in a campaign at 0% top of search: nothing to write
        out = self.plan(cfg=product(business_invest_log=log))
        self.assertFalse(self.step_downs(out))
        self.assertEqual(out['stop_loss'][0]['step_down'], 'nothing to write')
        self.assertFalse(T.by_type(out, 'Stop-loss review'))

    def test_business_stop_loss_needs_acos_at_breakeven_and_four_weeks(self):
        log = {'zebra cards': dict(since='2026-09-10', role='Invest', orders_then=3, owner_kind='business')}
        # orders up (3 -> 7), but ACOS 40% is over a $20 price's 25% breakeven: a step-down
        [row] = self.step_downs(self.plan(cfg=T.product(price=20.0, business_invest_log=log), keywords=self.HIGH_OWNER))
        self.assertIn('orders 3 -> 7, ACOS 40% against the 25% breakeven', row['stop_loss_reason'])
        # 27 days in: not judged yet, whatever its numbers; 28 days: judged
        log['zebra cards'].update(since='2026-09-22', orders_then=7)
        out = self.plan(cfg=product(business_invest_log=log), keywords=self.HIGH_OWNER)
        self.assertFalse(self.step_downs(out))
        self.assertFalse(out['stop_loss'])
        log['zebra cards']['since'] = '2026-09-21'
        self.assertTrue(self.step_downs(self.plan(cfg=product(business_invest_log=log), keywords=self.HIGH_OWNER)))

    def test_without_a_price_the_business_stop_loss_judges_orders_alone(self):
        # no price in the product file: no breakeven ACOS (budget_headroom.product_breakeven), so orders alone decide
        log = {'zebra cards': dict(since='2026-09-10', role='Invest', orders_then=7, owner_kind='business')}
        [row] = self.step_downs(self.plan(cfg=T.product(business_invest_log=log), keywords=self.HIGH_OWNER))
        self.assertIn('judged on orders alone', row['stop_loss_reason'])
        log['zebra cards']['orders_then'] = 3
        self.assertFalse(self.step_downs(self.plan(cfg=T.product(business_invest_log=log), keywords=self.HIGH_OWNER)))

    def test_a_business_stop_loss_with_no_owner_keyword_is_held_for_the_next_run(self):
        # the owner keyword is not in this run's keyword report: no step-down can be written, so it is held (decision 107)
        log = {'zebra cards': dict(since='2026-09-10', role='Invest', orders_then=7, owner_kind='business', campaign_id='108')}
        kws = [k for k in KEYWORDS if not (k['Keyword'] == 'zebra cards' and k['CampaignName'] in (B.B2B_EXACT, B2B_EXACT2))]
        out = self.plan(cfg=product(business_invest_log=log), keywords=kws)
        row = T.one(out, 'Stop-loss review', keyword='zebra cards')
        self.assertEqual((row['owner_kind'], row['lane'], row['row_id']), ('business', 'monitor', 'Stop-loss review:108::zebra cards'))
        self.assertIn("isn't in this run's keyword report", row['why'])

    def test_a_harvest_season_plans_no_business_stop_loss(self):
        log = {'zebra cards': dict(since='2026-09-10', role='Invest', orders_then=7, owner_kind='business')}
        out = self.plan(cfg=product(mode='harvest', business_invest_log=log), suggested_b=None)
        self.assertFalse(T.by_type(out, 'Stop-loss review'))
        self.assertFalse(out['stop_loss'])

    def test_each_log_has_its_own_stop_loss(self):
        # zebra cards in both logs: the consumer review judges organic rank and organic purchases at its month 3 checkpoint
        # (none read here), the business one orders and ACOS; two rows, one per kind, each with its own row id
        since = dict(since='2026-07-10', role='Invest', orders_then=7)   # past the consumer's month 3 checkpoint
        cfg = product(invest_log={'zebra cards': since},
                      business_invest_log={'zebra cards': dict(since, owner_kind='business', campaign_id='108')})
        out = self.plan(cfg=cfg, keywords=self.HIGH_OWNER)
        # the consumer search has no exact SKC in this fixture, so its step-down can't be written: a person's review; the
        # business one is stepped down by the run on its owner keyword (stop_loss.py, 2026-10-22)
        rows = {x.get('owner_kind') or 'consumer': x for x in T.by_type(out, 'Stop-loss review') if x['keyword'] == 'zebra cards'}
        self.assertEqual(sorted(rows), ['consumer'])
        self.assertEqual(rows['consumer']['row_id'], 'Stop-loss review:::zebra cards')
        self.assertIn('organic rank', rows['consumer']['why'])
        [business] = self.step_downs(out)
        self.assertIn('B2B campaign', business['stop_loss_reason'])
        self.assertEqual(sorted(s.get('owner_kind', 'consumer') for s in out['stop_loss']), ['business', 'consumer'])
        self.assertNotIn('owner_kind', next(s for s in out['stop_loss'] if 'rank_then' in s))

    # --- Final fix wave (2026-10-21) --------------------------------------------------------------------------------------
    def test_a_group_member_with_a_budget_override_goes_out_at_it(self):   # I1
        # office cards (908) is the higher-opportunity head of campaign 108's business invests; zebra cards rides it as a
        # member with a $25 budget override. Since decision 107 (2026-10-23) an override is the search's standard budget,
        # so the group goes out and the campaign update writes $25 (until then the override sent the group to a person)
        kws = KEYWORDS + [T.keyword('908', 'office cards', 'exact', B.B2B_EXACT, 1.00, 16, 4, 14)]
        sts = SEARCH_TERMS + [T.search_term('office cards', B.B2B_EXACT, 16, 4, 14)]
        out = self.plan(cfg=product(budget_overrides={'zebra cards': 25}), keywords=kws, search_terms=sts)
        rows = {x['keyword']: x for x in T.by_type(out, 'Business invest') if x['campaign_id'] == '108'}
        head, member = rows['office cards'], rows['zebra cards']
        self.assertEqual((member['budget'], member['campaign_budget']), (25, 25))
        self.assertGreater(head['opportunity'], member['opportunity'])
        self.assertEqual((head['lane'], member['lane']), ('auto', 'auto'))
        self.assertNotIn('written at the standard', member['lane_reason'])

    def assert_home_from_the_keyword_report(self, out):
        """The New exact keyword of office cards goes into campaign 110 as the keyword report names it (keyword 906's
        campaign and ad group), as a campaign not read live: no budget in its update, the budget-unread note in its how;
        and the Scale Insights row moves 110 to the exact-owners strategy with the other B2B campaigns the report names."""
        row = T.one(out, 'New exact keyword', keyword='office cards')
        self.assertEqual((row['campaign'], row['campaign_id'], row['ad_group_id'], row['budget_now'], row['campaign_budget']),
                         (B2B_STWS_EXACT, '110', '210', None, None))
        self.assertIn('not read live', row['how'])   # the placement review holds it too: the keyword at its bid only
        files = dict(planner.payload_entries(out['changes'], self.shared(), T.ASIN))
        self.assertEqual([e['keywordText'] for _, e in files['1c_new_keywords.json']], ['office cards'])
        self.assertFalse([e for _, e in files.get('5_campaign_updates.json', []) if e['campaignId'] == '110' and 'budget' in e])
        self.assertIn(dict(keyword='office cards', campaign_id='110', ad_group_id='210'), out['checks'])
        owners, others = T.one(out, 'Scale Insights rules', owner_kind='business')['new'].split('; ')
        self.assertIn(B2B_STWS_EXACT, owners)
        for name in (B.B2B_STWS, B2B_EXACT2):
            self.assertIn(name, others)

    def test_a_marker_campaign_missing_from_campaigns_json_is_a_home_not_read_live(self):   # I2, ruling 18
        # campaign 110 ("... B2B - Search Terms with Sales - Exact - 1") holds keyword 906 in the keyword report but is not
        # in campaigns.json: it exists, so the row never asks a person to build it
        out = self.plan(more_campaigns=[c for c in CAMPAIGNS if c['name'] != B2B_STWS_EXACT])
        self.assert_home_from_the_keyword_report(out)

    def test_without_campaigns_json_the_keyword_report_names_the_b2b_campaigns(self):     # I2, ruling 18
        T.make_run(self.run_dir, extra={'suggested_bids_business.json': SUGGESTED_B}, queries=QUERIES, search_terms=SEARCH_TERMS,
                   keywords=KEYWORDS, more_campaigns=CAMPAIGNS, suggested=SUGGESTED)
        os.remove(os.path.join(self.run_dir, 'campaigns.json'))
        out = planner.build(T.ASIN, product(), self.shared(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)
        self.assert_home_from_the_keyword_report(out)
        self.assertIn(B.B2B_EXACT, T.one(out, 'Scale Insights rules', owner_kind='business')['new'].split('; ')[0])

    def test_no_marker_campaign_at_all_says_check_the_ads_console(self):                   # I2, ledger (Task 2)
        # no campaign with the marker in campaigns.json or in the keyword report (906 dropped): the row says to check the
        # Ads console before building one, carries no payload, and puts no check with no ids on the checks list
        camps = [c for c in CAMPAIGNS if c['name'] != B2B_STWS_EXACT]
        out = self.plan(more_campaigns=camps, keywords=[k for k in KEYWORDS if k['KeywordId'] != '906'])
        row = T.one(out, 'New exact keyword', keyword='office cards')
        self.assertEqual((row['campaign_id'], row['ad_group_id']), (None, None))
        self.assertIn('No enabled B2B campaign named "B2B - Search Terms with Sales - Exact" in campaigns.json (not read, or '
                      'none exists): check the Ads console before building one', row['how'])
        self.assertNotIn('a person builds one', row['how'])
        files = dict(planner.payload_entries(out['changes'], self.shared(), T.ASIN))
        self.assertNotIn('1c_new_keywords.json', files)
        self.assertFalse([e for _, e in files.get('5_campaign_updates.json', []) if e.get('campaignId') in (None, 'None')])
        self.assertFalse([c for c in out['checks'] if c['campaign_id'] is None])

    def test_summary_counts_the_business_stop_loss_reviews_and_scale_insights_rows(self):   # ruling 14 (spec section 6)
        business = self.plan()['summary'][0]['business']
        self.assertEqual((business['si_rows'], business['stop_loss_reviews']), (1, 0))
        log = {'zebra cards': dict(since='2026-09-10', role='Invest', orders_then=7, clicks_then=20, owner_kind='business')}
        business = self.plan(cfg=product(business_invest_log=log), keywords=self.HIGH_OWNER)['summary'][0]['business']
        # since 2026-10-22 the run steps the search down itself: a step-down, no review for a person
        self.assertEqual((business['si_rows'], business['stop_loss_reviews'], business['stop_loss_step_downs']), (1, 0, 1))


if __name__ == '__main__':
    unittest.main()
