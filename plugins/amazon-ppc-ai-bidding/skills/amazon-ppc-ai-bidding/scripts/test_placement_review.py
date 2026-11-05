import copy
import json
import pathlib
import tempfile
import unittest

import placement_review as placements
import plan as planner

SKILL = pathlib.Path(__file__).resolve().parents[1]
SHARED = json.loads((SKILL / 'config.json').read_text(encoding='utf-8'))
PRODUCT = dict(asin='B0SAMP0025', profit_per_unit=4, economics_as_of='2026-10-18')
TODAY = '2026-10-18'


def fixture():
    campaign = dict(campaignId='123', name='ASIN exact campaign', state='ENABLED', optimizations={'bidSettings':{'bidStrategy':'SALES_DOWN_ONLY','bidAdjustments':{'placementBidAdjustments':[{'placement':'TOP_OF_SEARCH','percentage':0}, {'placement':'SITE_AMAZON_BUSINESS','percentage':40}]}}})
    row = dict(asin=PRODUCT['asin'], campaignId='123', placement='Top of Search on-Amazon')
    for suffix in ('30', '90', '_recent'):
        row.update({key + suffix:value for key,value in dict(clicks=60, orders=12, spend=24, sales=120).items()})
    return dict(asin=PRODUCT['asin'], complete=True, as_of=TODAY, retrieved_at=TODAY + 'T18:00:00+08:00',
                windows={'30d':['2026-09-04','2026-10-03'],'90d':['2026-07-06','2026-10-03'],'recent':['2026-09-18','2026-10-17']},
                campaigns=[campaign], live_asins={'123':[PRODUCT['asin']]}, rows=[row])


def first(data=None, changes=None, product=None):
    return placements.recommend({'changes':changes or []}, product or PRODUCT, SHARED, data or fixture(), TODAY)['rows'][0]


# The standing rank top-of-search policy (Kim, 2026-10-20), pinned here so retuning config.json can't break the tests.
POLICY_ON = dict(invest_tos_pct=50, prove_tos_pct=30, rank_tos_standing=dict(approved=True, by='Kim', on='2026-10-20'))
POLICY_OFF = dict(POLICY_ON, rank_tos_standing=dict(approved=False, by='Kim', on='2026-10-20'))


def rank_rows():
    """The three rank-investment rows hold_defaults sees, as plan.py builds them: planner TOS +50 / +30 on each."""
    return [dict(type='Budget and top of search', campaign_id='123', campaign='Existing', keyword='cards', role='Invest', budget=10, tos=50, tos_now=0,
                 other_placements=[]),
            dict(type='New exact campaign', campaign='New', keyword='thank you cards', role='Prove first', new=.5, budget=5, tos=30, tos_bid=.65),
            dict(type='Reuse exact campaign', campaign_id='123', campaign='Existing exact', keyword='cards exact', role='Invest', new=.4, budget=10, tos=50)]


def live_with_other_placements():
    data = fixture()
    data['campaigns'][0]['optimizations']['bidSettings']['bidAdjustments']['placementBidAdjustments'] += [
        dict(placement='REST_OF_SEARCH', percentage=15), dict(placement='PRODUCT_PAGE', percentage=20)]
    return data['campaigns']


class PlacementTests(unittest.TestCase):
    def test_rank_proposal_cannot_generate_apply_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'preview-only'):
                planner.write_outputs(directory, {'changes': [{'rank_investment_experiment': True}]}, SHARED, PRODUCT['asin'])
            self.assertFalse((pathlib.Path(directory) / 'payloads').exists())

    def test_profitable_placement_bounded_boost(self):
        row = first()
        self.assertEqual((row['status'], row['current'], row['proposed']), ('recommend', 0, 25))
        self.assertAlmostEqual(row['breakeven_cpc'], .8)
        self.assertEqual(row['review_on'], '2026-11-15')
        self.assertIn('scenario', row['assumption'])

    def test_costly_placement_bounded_cut_preserves_other_settings(self):
        data = fixture()
        data['campaigns'][0]['optimizations']['bidSettings']['bidAdjustments']['placementBidAdjustments'][0]['percentage'] = 100
        data['rows'][0].update(spend30=120, spend_recent=120)
        before = copy.deepcopy(data)
        row = first(data)
        self.assertEqual((row['status'], row['proposed']), ('recommend', 75))
        self.assertEqual(data, before)

    def test_zero_floor_no_negative_modifiers(self):
        data = fixture()
        data['rows'][0].update(spend30=120, spend_recent=120)
        row = first(data)
        self.assertEqual((row['status'], row['proposed'], row['reason_code']), ('hold', 0, 'no_modifier_headroom'))

    def test_thin_and_missing_stay_held(self):
        data = fixture()
        data['rows'][0].update(clicks30=4, orders30=1, clicks90=5, orders90=1)
        self.assertEqual(first(data)['reason_code'], 'thin_data')
        result = placements.recommend({'changes':[]}, PRODUCT, SHARED, None, TODAY)
        self.assertEqual(result['status'], 'missing_data')

    def test_fallback_and_recent_activity(self):
        data = fixture()
        data['rows'][0].update(clicks30=5, orders30=1)
        self.assertEqual(first(data)['window'], '90d')
        data['rows'][0]['clicks_recent'] = 0
        self.assertEqual(first(data)['reason_code'], 'stale_traffic')

    def test_zero_orders_never_boost_even_if_pooled_cvr_high(self):
        data = fixture()
        data['rows'][0].update(orders30=0, spend30=.01, orders_recent=0)
        extra = dict(data['rows'][0], placement='Detail Page on-Amazon', orders30=50)
        data['rows'].append(extra)
        self.assertEqual(first(data)['status'], 'hold')

    def test_recent_conflict_and_base_change_hold(self):
        data = fixture()
        data['rows'][0].update(orders_recent=0)
        self.assertEqual(first(data)['reason_code'], 'recent_conflict')
        self.assertEqual(first(changes=[{'type':'Bid change','campaign_id':'123'}])['reason_code'], 'base_or_mix_changes')

    def test_preserve_amc_shared_and_dynamic_settings(self):
        data = fixture()
        data['campaigns'][0]['name'] = 'AMC Low Bids'
        self.assertEqual(first(data)['reason_code'], 'audience_excluded')
        data = fixture()
        data['live_asins']['123'].append('B0SAMP0016')
        self.assertEqual(first(data)['reason_code'], 'scope_unverified')
        data = fixture()
        data['campaigns'][0]['optimizations']['bidSettings']['bidStrategy'] = 'SALES_UP_AND_DOWN'
        self.assertEqual(first(data)['reason_code'], 'strategy_review')

    def test_business_campaigns_are_priced_like_any_other(self):
        # Kim, 2026-10-21 (design 2026-10-21-b2b-lane-and-roles 4e): an Amazon Business campaign (the live flag or the B2B
        # name marker) is judged on its placement economics like any other campaign, no longer held as live; the fixture's
        # verdict is a bounded +25% test. An audience campaign is still held.
        verdict = first()
        for name, flagged in ((f"Cards - {PRODUCT['asin']} - B2B Launch Targets - Exact - 1", True),
                              (f"Cards - {PRODUCT['asin']} - Launch Targets - Exact - 9", True),
                              (f"Cards - {PRODUCT['asin']} - B2B Launch Targets - Exact - 1", False)):
            with self.subTest(name=name, flagged=flagged):
                data = fixture()
                data['campaigns'][0]['name'] = name
                if flagged:
                    data['campaigns'][0]['siteRestrictions'] = ['AMAZON_BUSINESS']
                row = first(data)
                self.assertNotEqual(row['reason_code'], 'business_excluded')
                self.assertEqual((row['status'], row['reason_code'], row['proposed']),
                                 (verdict['status'], verdict['reason_code'], verdict['proposed']))
        # a B2B campaign whose owner keyword a Business invest row re-bids this run is changing, as a reused exact campaign
        # is, even when its top of search stays where it is: no second modifier on it
        data = fixture()
        data['campaigns'][0].update(name=f"Cards - {PRODUCT['asin']} - B2B Launch Targets - Exact - 1", siteRestrictions=['AMAZON_BUSINESS'])
        invest = dict(type='Business invest', campaign_id='123', owner_kind='business', tos=0, tos_now=0)
        self.assertEqual(first(data, changes=[invest])['reason_code'], 'base_or_mix_changes')
        # and so is one whose owner is already invested as planned (plan.py's business_live_invests: no row, but its
        # campaign runs the policy top of search the invest needs): no proposal under it
        live = [dict(keyword='zebra cards', role='Invest', campaign_id='123', tos=50, budget=10)]
        review = placements.recommend({'changes': [], 'business_live_invests': live}, PRODUCT, SHARED, data, TODAY)
        self.assertEqual(review['rows'][0]['reason_code'], 'base_or_mix_changes')
        data = fixture()
        data['campaigns'][0]['name'] = 'AMC Low Bids'
        self.assertEqual(first(data)['reason_code'], 'audience_excluded')

    def test_stale_economics_and_cap(self):
        self.assertEqual(first(product=dict(PRODUCT, economics_as_of='2026-09-01'))['reason_code'], 'stale_or_missing')
        data = fixture()
        data['campaigns'][0]['optimizations']['bidSettings']['bidAdjustments']['placementBidAdjustments'][0]['percentage'] = 150
        self.assertEqual(first(data)['reason_code'], 'positive_cap')

    def test_maturity_and_window_validation(self):
        data = fixture()
        data['windows']['90d'][1] = TODAY
        with self.assertRaises(ValueError):
            first(data)
        data = fixture()
        data['windows']['30d'][0] = '2026-09-01'
        with self.assertRaises(ValueError):
            first(data)

    def test_input_scope_duplicates_and_invalid_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'placement_inputs.json'
            for modification in ('asin', 'duplicate', 'invalid'):
                data = fixture()
                if modification == 'asin': data['asin'] = 'B0SAMP0016'
                if modification == 'duplicate': data['rows'].append(copy.deepcopy(data['rows'][0]))
                if modification == 'invalid': data['rows'][0]['clicks30'] = -1
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    placements.read_inputs(directory, PRODUCT['asin'])

    def test_payloads_never_write_held_placements_or_strategy(self):
        changes = [{'type':'Budget and top of search','campaign_id':'123','tos':50,'budget':10},
                   {'type':'New exact campaign','campaign':'New','keyword':'cards','new':.5,'budget':10,'tos':50},
                   {'type':'Reuse exact campaign','campaign_id':'123','campaign':'Existing','keyword':'cards exact','new':.4,'budget':5,'tos':50}]
        placements.hold_defaults(changes, fixture()['campaigns'])
        self.assertEqual([row['tos'] for row in changes], [0, 0, 0])
        out = dict(changes=changes, terms=[], checks=[], placement_review=placements.recommend({'changes':changes}, PRODUCT, SHARED, fixture(), TODAY))
        with tempfile.TemporaryDirectory() as directory:
            planner.write_outputs(directory, out, SHARED, PRODUCT['asin'])
            updates = json.loads((pathlib.Path(directory) / 'payloads/review/5_campaign_updates.json').read_text())
            self.assertNotIn('dynamicBidding', updates[0])
            self.assertNotIn('optimizations', updates[0])
            created = json.loads((pathlib.Path(directory) / 'payloads/review/1_new_campaigns.json').read_text())
            self.assertEqual(created[0]['dynamicBidding']['placementBidding'][0]['percentage'], 0)
            reused = json.loads((pathlib.Path(directory) / 'payloads/review/2_reuse_specs.json').read_text())
            self.assertNotIn('tos', reused[0])
            self.assertTrue(reused[0]['placement_hold'])
            self.assertIn('placement_review', json.loads((pathlib.Path(directory) / 'plan.json').read_text()))

    # --- the standing rank top-of-search policy (Kim, 2026-10-20) -----------------------------------------------------
    def test_standing_policy_is_in_the_live_config(self):
        standing = SHARED['placement']['rank_tos_standing']
        self.assertIs(standing['approved'], True)
        self.assertEqual((standing['by'], standing['on']), ('Kim', '2026-10-20'))
        self.assertEqual((SHARED['placement']['invest_tos_pct'], SHARED['placement']['prove_tos_pct']), (50, 30))
        self.assertTrue(SHARED['placement']['recommendations']['enabled'])  # the economics review stays on

    def test_flag_off_keeps_todays_holds(self):
        for label, placement in (('no placement given', None), ('flag false', POLICY_OFF), ('no flag block', dict(invest_tos_pct=50, prove_tos_pct=30)),
                                 ('flag not exactly true', dict(POLICY_ON, rank_tos_standing=dict(approved='yes')))):
            with self.subTest(label):
                changes = rank_rows()
                if placement is None:
                    placements.hold_defaults(changes, fixture()['campaigns'])
                else:
                    placements.hold_defaults(changes, fixture()['campaigns'], placement)
                self.assertEqual([row['tos'] for row in changes], [0, 0, 0])
                self.assertEqual([row.get('placement_hold') for row in changes], [True, True, True])
                self.assertNotIn('rank_tos_standing', json.dumps(changes))
                self.assertEqual(changes[1]['placement_note'], 'No campaign history: start at 0% for all placements.')

    def test_standing_policy_sets_rank_top_of_search_and_keeps_other_placements(self):
        campaigns = live_with_other_placements()
        before = copy.deepcopy(campaigns)
        changes = rank_rows()
        placements.hold_defaults(changes, campaigns, POLICY_ON)
        budget, new, reuse = changes
        self.assertEqual((budget['tos'], budget['tos_now']), (50, 0))
        self.assertEqual((new['tos'], new['tos_now'], new['tos_bid']), (30, None, .65))
        self.assertEqual((reuse['tos'], reuse['tos_now'], reuse['tos_bid']), (50, 0, .6))
        for row in changes:
            self.assertNotIn('placement_hold', row)
            self.assertIs(row['rank_tos_standing'], True)
            self.assertIn('standing policy', row['placement_note'])
        live_others = [dict(placement='SITE_AMAZON_BUSINESS', percentage=40), dict(placement='REST_OF_SEARCH', percentage=15),
                       dict(placement='PRODUCT_PAGE', percentage=20)]
        self.assertEqual(budget['other_placements'], live_others)  # rest of search, product pages and Business: as live
        self.assertEqual(reuse['other_placements'], live_others)
        self.assertNotIn('other_placements', new)  # a new campaign starts every other placement at 0%
        self.assertEqual(campaigns, before)  # the live snapshot is only read

    def test_standing_policy_payloads_write_the_policy_and_the_live_others(self):
        changes = rank_rows()
        placements.hold_defaults(changes, live_with_other_placements(), POLICY_ON)
        out = dict(changes=changes, terms=[], checks=[], placement_review=placements.recommend({'changes': changes}, PRODUCT, SHARED, fixture(), TODAY))
        with tempfile.TemporaryDirectory() as directory:
            planner.write_outputs(directory, out, SHARED, PRODUCT['asin'])
            folder = pathlib.Path(directory) / 'payloads/review'
            updates = json.loads((folder / '5_campaign_updates.json').read_text())
            self.assertEqual(updates[0]['dynamicBidding']['placementBidding'],
                             [dict(placement='PLACEMENT_TOP', percentage=50), dict(placement='SITE_AMAZON_BUSINESS', percentage=40),
                              dict(placement='PLACEMENT_REST_OF_SEARCH', percentage=15), dict(placement='PLACEMENT_PRODUCT_PAGE', percentage=20)])
            created = json.loads((folder / '1_new_campaigns.json').read_text())
            self.assertEqual(created[0]['dynamicBidding']['placementBidding'], [dict(placement='PLACEMENT_TOP', percentage=30)])
            reused = json.loads((folder / '2_reuse_specs.json').read_text())
            self.assertEqual(reused[0]['tos'], 50)
            self.assertNotIn('placement_hold', reused[0])
            self.assertEqual(reused[0]['other_placements'], [dict(placement='SITE_AMAZON_BUSINESS', percentage=40),
                                                             dict(placement='REST_OF_SEARCH', percentage=15), dict(placement='PRODUCT_PAGE', percentage=20)])

    def test_standing_policy_leaves_other_roles_held(self):
        changes = rank_rows()
        for row, role in zip(changes, ('Hold', None, 'Trim')):
            row['role'] = role
        placements.hold_defaults(changes, fixture()['campaigns'], POLICY_ON)
        self.assertEqual([row['tos'] for row in changes], [0, 0, 0])
        self.assertEqual([row['placement_hold'] for row in changes], [True, True, True])

    def test_standing_policy_leaves_placement_experiment_campaigns_alone(self):
        data = fixture()
        data['campaigns'][0]['optimizations']['bidSettings']['bidAdjustments']['placementBidAdjustments'][0]['percentage'] = 900
        changes = rank_rows()
        changes[0]['campaign'] = changes[2]['campaign'] = 'Cards - Exact SKC - cards - TOS 900%'
        changes[1]['campaign'] = 'Cards - Exact SKC - 900% TOS test'
        placements.hold_defaults(changes, data['campaigns'], POLICY_ON)
        self.assertEqual([row['tos'] for row in changes], [900, 0, 900])  # held at the live setting, new ones at 0%
        self.assertEqual([row['placement_hold'] for row in changes], [True, True, True])
        self.assertIn('placement experiment', changes[0]['placement_note'])
        # the planner's own rank campaigns end in "TOS Rank": that is not an experiment marker
        changes = rank_rows()
        changes[0]['campaign'] = changes[2]['campaign'] = 'Cards - Exact SKC - cards - TOS Rank'
        changes[1]['campaign'] = 'Cards - Exact SKC - thank you cards - TOS Rank'
        placements.hold_defaults(changes, data['campaigns'], POLICY_ON)
        self.assertEqual([row['tos'] for row in changes], [50, 30, 50])

    def test_standing_policy_holds_what_it_cannot_write_safely(self):
        # the payload writes down-only bidding and only placementBidding, so a campaign on another strategy, with audience
        # adjustments or not read live stays exactly as it is
        cases = {}
        up_down = fixture()
        up_down['campaigns'][0]['optimizations']['bidSettings']['bidStrategy'] = 'SALES_UP_AND_DOWN'
        cases['up and down'] = up_down['campaigns']
        audience = fixture()
        audience['campaigns'][0]['optimizations']['bidSettings']['bidAdjustments']['audienceBidAdjustments'] = [dict(audience='AMC', percentage=-60)]
        cases['audience'] = audience['campaigns']
        global_campaign = fixture()
        global_campaign['campaigns'][0]['globalCampaignId'] = 'g1'
        cases['global'] = global_campaign['campaigns']
        cases['not read live'] = []
        for label, campaigns in cases.items():
            with self.subTest(label):
                changes = rank_rows()
                placements.hold_defaults(changes, campaigns, POLICY_ON)
                budget, new, reuse = changes
                self.assertTrue(budget['placement_hold'] and reuse['placement_hold'])
                self.assertNotIn('rank_tos_standing', json.dumps([budget, reuse]))
                self.assertIn('standing', budget['placement_note'])  # says why the policy did not apply
                self.assertEqual((new['tos'], new['tos_bid']), (30, .65))  # a new campaign needs no live settings

    def test_standing_policy_needs_a_usable_percentage(self):
        for bad in (None, -5, 901, True, 'fifty', float('nan')):
            with self.subTest(bad):
                changes = rank_rows()
                placements.hold_defaults(changes, fixture()['campaigns'], dict(POLICY_ON, invest_tos_pct=bad, prove_tos_pct=bad))
                self.assertEqual([row['tos'] for row in changes], [0, 0, 0])

    def test_standing_policy_marks_a_budget_row_that_only_sets_top_of_search(self):
        # policy_tos_only: the budget is unchanged, so the only change is top of search to the policy (the lanes read it)
        def budget_row(**over):
            row = dict(rank_rows()[0], budget_now=10)
            row.update(over)
            return row
        rows = [budget_row(), budget_row(budget_now=8), budget_row(role='Prove first', budget=5, budget_now=5, tos=30), budget_row(budget_now=None)]
        placements.hold_defaults(rows, fixture()['campaigns'], POLICY_ON)
        self.assertEqual([row.get('policy_tos_only') for row in rows], [True, False, True, False])
        self.assertEqual([row['tos'] for row in rows], [50, 50, 30, 50])  # the budget change still gets the policy top of search
        # no other row type carries it, and nothing carries it with the flag off or when the policy leaves the campaign alone
        others = rank_rows()[1:]
        placements.hold_defaults(others, fixture()['campaigns'], POLICY_ON)
        self.assertEqual([row.get('policy_tos_only') for row in others], [None, None])
        for label, placement, campaigns in (('flag off', POLICY_OFF, fixture()['campaigns']), ('no placement', None, fixture()['campaigns']),
                                            ('not read live', POLICY_ON, [])):
            with self.subTest(label):
                held = [budget_row()]
                placements.hold_defaults(held, campaigns, placement) if placement is not None else placements.hold_defaults(held, campaigns)
                self.assertFalse(held[0].get('policy_tos_only'))
                self.assertTrue(held[0]['placement_hold'])
        # a row marked on the first pass loses it when the second pass (the placement snapshot) holds the campaign
        row = budget_row()
        placements.hold_defaults([row], fixture()['campaigns'], POLICY_ON)
        self.assertIs(row['policy_tos_only'], True)
        up_down = fixture()['campaigns']
        up_down[0]['optimizations']['bidSettings']['bidStrategy'] = 'SALES_UP_AND_DOWN'
        placements.hold_defaults([row], up_down, POLICY_ON)
        self.assertFalse(row['policy_tos_only'])

    def test_standing_policy_is_the_same_when_planned_twice(self):
        # plan.py calls hold_defaults in build() on campaigns.json and again in main() on the placement snapshot
        once, twice = rank_rows(), rank_rows()
        placements.hold_defaults(once, live_with_other_placements(), POLICY_ON)
        placements.hold_defaults(twice, live_with_other_placements(), POLICY_ON)
        placements.hold_defaults(twice, live_with_other_placements(), POLICY_ON)
        self.assertEqual(once, twice)

    def test_standing_policy_shows_in_the_placement_review(self):
        shared = dict(SHARED, placement=dict(SHARED['placement'], **POLICY_ON))
        changes = rank_rows()
        placements.hold_defaults(changes, fixture()['campaigns'], POLICY_ON)
        review = placements.recommend({'changes': changes}, PRODUCT, shared, fixture(), TODAY)
        new_rows = {row['placement']: row for row in review['rows'] if row['campaign'] == 'New'}
        self.assertEqual((new_rows['TOP_OF_SEARCH']['proposed'], new_rows['PRODUCT_PAGE']['proposed'], new_rows['REST_OF_SEARCH']['proposed']), (30, 0, 0))
        self.assertIn('standing policy', new_rows['TOP_OF_SEARCH']['reason'])
        self.assertEqual(new_rows['PRODUCT_PAGE']['reason_code'], 'new_campaign')
        # the plan sets this live campaign's top of search, so the economics review holds it rather than propose a second change
        existing = [row for row in review['rows'] if row['campaign_id'] == '123' and row['placement'] == 'TOP_OF_SEARCH'][0]
        self.assertEqual(existing['reason_code'], 'base_or_mix_changes')
        # a budget-only row (top of search already at the policy) does not stop the review
        data = fixture()
        data['campaigns'][0]['optimizations']['bidSettings']['bidAdjustments']['placementBidAdjustments'][0]['percentage'] = 50
        budget_only = [rank_rows()[0]]
        placements.hold_defaults(budget_only, data['campaigns'], POLICY_ON)
        self.assertEqual((budget_only[0]['tos'], budget_only[0]['tos_now']), (50, 50))
        review = placements.recommend({'changes': budget_only}, PRODUCT, shared, data, TODAY)
        self.assertNotEqual(review['rows'][0]['reason_code'], 'base_or_mix_changes')

    def test_preview_escapes_and_exposes_all_holds(self):
        data = fixture()
        data['campaigns'][0]['name'] = '<script>alert(1)</script>'
        page = placements.preview_html(placements.recommend({'changes':[]}, PRODUCT, SHARED, data, TODAY))
        self.assertNotIn('<script>', page)
        self.assertIn('Rest of search', page)
        self.assertIn('separate', page.lower())


if __name__ == '__main__':
    unittest.main()
