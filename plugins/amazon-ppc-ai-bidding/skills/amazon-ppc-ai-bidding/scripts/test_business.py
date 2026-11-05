"""Business (B2B) campaigns as their own shopper kind: the kind classifier, the Business family, the config markers,
and the planner pricing business keywords on their own conversion.

The team's B2B campaigns are Amazon-Business-exclusive (siteRestrictions AMAZON_BUSINESS, "B2B" in the name) and
convert about twice as well as the consumer campaigns, so they are priced on their own conversion, never read as
consumer duplicates (docs/superpowers/specs/2026-10-21-amc-b2b-fold-design.md).
"""
import os
import tempfile
import unittest

import dashboard
import plan as planner
import plan_lanes
import test_plan_lanes as T
import test_visibility as V

B2B_EXACT = f'Cards - {T.ASIN} - B2B Launch Targets - Exact - 1'
B2B_STWS = f'Cards - {T.ASIN} - B2B - Search Terms with Sales - Phrase - 1'
FLAGGED_ONLY = f'Cards - {T.ASIN} - Launch Targets - Exact - 9'   # no marker in the name, flag on the campaign
SB_B2B_VIDEO = f'Cards - {T.ASIN} - Videos - B2B Launch Targets - Exact - 1'
T.IDS[B2B_EXACT] = ('108', '208')   # campaign and ad group ids, looked up by name by the fixture helpers
T.IDS[B2B_STWS] = ('109', '209')
B2B_SKC = f'Cards - {T.ASIN} - B2B - Exact SKC - blank cards - TOS Rank'   # a B2B campaign named like the consumer SKC
T.IDS[B2B_SKC] = ('110', '210')
T.IDS[FLAGGED_ONLY] = ('111', '211')

# 'zebra cards' beats the market (an invest search), so the planner needs Amazon's suggestion for it. 'blank cards' gets a
# $1.50 high here, above anything its business keyword bids
ZEBRA = {'zebra cards': [0.40, 0.60, 0.80]}
SUGGESTED = dict(T.SUGGESTED, **{'blank cards': [0.55, 0.70, 1.50]}, **ZEBRA)
QUERIES = T.QUERIES + [T.query('zebra cards', 600, 240, 24, 20, 5)]
SEARCH_TERMS = T.SEARCH_TERMS + [T.search_term('blank cards', B2B_EXACT, 40, 3, 30.0)]
KEYWORDS = T.KEYWORDS + [
    T.keyword('901', 'blank cards', 'exact', B2B_EXACT, 1.05, 40, 3, 30.0),        # B2B copy of the promoted search
    T.keyword('902', 'zebra cards', 'exact', B2B_EXACT, 1.05, 35, 0, 20.0),        # trails the market badly on its own clicks
    T.keyword('903', 'bulk thank you cards', 'phrase', B2B_STWS, 1.30, 2, 0, 1.0)]  # no SQP row, no search-term row
# a Sponsored Brands B2B video campaign WITHOUT siteRestrictions: the SB inventory read lacks it, the name marker must carry
SB_FILES = {'sb_campaigns_p1.json': {'items': [dict(campaignId='501', name=SB_B2B_VIDEO, state='ENABLED', budget=10)]},
            'sb_keywords_p1.json': {'items': [dict(keywordId='601', campaignId='501', adGroupId='701', keywordText='blank cards',
                                                   matchType='EXACT', state='ENABLED', bid=0.80)]},
            'sb_kw_perf.json': {'data': []}}


class CampaignKind(unittest.TestCase):
    def test_kind_from_flag_marker_and_default(self):
        kind = planner.kind_fn(T.shared_config(), [dict(name=FLAGGED_ONLY, siteRestrictions=['AMAZON_BUSINESS'])])
        self.assertEqual(kind(FLAGGED_ONLY), 'business')
        self.assertEqual(kind(B2B_STWS), 'business')            # by marker, no campaign record at all
        self.assertEqual(kind(T.LOW), 'audience')
        self.assertEqual(kind(T.STW), 'consumer')
        self.assertEqual(kind(f'Cards - {T.ASIN} - B2B - Low Bids - 1'), 'business')   # business wins over audience

    def test_family_business_wins_over_search_terms_w_sales(self):
        kind = planner.kind_fn(T.shared_config(), [])
        self.assertEqual(planner.family_fn(T.product(), T.shared_config(), kind)(B2B_STWS), 'Business')
        self.assertEqual(planner.family_fn(T.product(), T.shared_config())(T.STW), 'Search terms w sales')

    def test_config_markers(self):
        self.assertNotIn('B2B', T.CONFIG['audience_campaign_markers'])
        self.assertEqual(T.CONFIG['b2b_campaign_markers'], ['B2B'])


class ScopeMap(unittest.TestCase):
    def test_every_lever_is_named_and_b2b_is_on_the_map(self):
        # the dashboard's optimisation map (dashboard.build_scope) reads id, label, what and the ai status of each lever
        for lever in T.CONFIG['scope']:
            self.assertTrue(all(lever.get(k) for k in ('id', 'label', 'what', 'ai')), lever.get('id'))
        b2b = [lever for lever in T.CONFIG['scope'] if lever['id'] == 'b2b']
        self.assertEqual(len(b2b), 1)
        # business rows take every role and the same lanes as consumer rows (design 2026-10-21-b2b-lane-and-roles 6): the
        # lever counts the business invest, its copies, negatives, new keywords, stop-loss and Scale Insights rows too
        self.assertEqual((b2b[0]['types'], b2b[0]['ai']),
                         (['Business invest', 'Bid change', 'Pause keyword', 'Negative exact', 'New exact keyword',
                           'Stop-loss review', 'Scale Insights rules'], 'ai'))
        self.assertEqual(b2b[0]['owner_kind'], 'business')   # counts only business rows on the public map (ruling 10)
        what = b2b[0]['what']
        self.assertIn("inside the team's B2B campaigns", what)
        self.assertIn('the same lanes as consumer rows', what)
        self.assertNotIn('until the Nov 9 gate', what)       # the business-only human rule is gone (rulebook 9.4)

    def test_a_lever_with_an_owner_kind_counts_only_its_rows(self):
        # the b2b lever shares its types with keyword_bids: by type alone it would repeat the consumer count on every product
        types = ['Bid change', 'Pause keyword']
        cfg = {'scope': [dict(id='b2b', label='B2B', what='w', ai='ai', types=types, owner_kind='business'),
                         dict(id='keyword_bids', label='Bids', what='w', ai='ai', types=types)]}
        changes = [dict(type='Bid change', owner_kind='business'), dict(type='Bid change'), dict(type='Bid change')]
        rows = {r['id']: r for r in dashboard.build_scope(cfg, {}, 'ai', changes, '2026-10-21', 'proposed', 'Weekly run')}
        self.assertEqual((rows['b2b']['last_change']['n'], rows['b2b']['last_change']['types']), (1, ['Bid change']))
        self.assertEqual((rows['keyword_bids']['last_change']['n'], rows['keyword_bids']['last_change']['types']),
                         (3, ['Bid change']))
        # a product with no business row: the b2b lever shows no change at all
        rows = {r['id']: r for r in dashboard.build_scope(cfg, {}, 'ai', changes[1:], '2026-10-21', 'proposed', 'Weekly run')}
        self.assertNotIn('last_change', rows['b2b'])
        self.assertEqual(rows['keyword_bids']['last_change']['n'], 2)

    def test_a_page_refresh_still_counts_business_rows(self):
        # `refresh` rebuilds the map from the page's published change rows (CHANGE_KEYS), so they must keep owner_kind
        self.assertIn('owner_kind', dashboard.CHANGE_KEYS)
        live = {'asin': T.ASIN, 'card': {}, 'run': {'date': '2026-10-21', 'state': 'proposed', 'label': 'Weekly run', 'changes': [
            dict(type='Bid change', owner_kind='business'), dict(type='Bid change'), dict(type='Pause keyword')]}}
        doc = dashboard.refresh_doc(live, dict(asin=T.ASIN, sku='test', product='Test'), T.CONFIG, 'Test')
        rows = {r['id']: r for r in doc['scope']}
        self.assertEqual(rows['b2b']['last_change']['n'], 1)
        self.assertEqual(rows['keyword_bids']['last_change']['n'], 3)


class BusinessPricing(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = os.path.join(tmp.name, 'run')

    def plan(self, sb=False, **over):
        """Plan the fixture with its two B2B campaigns (and, with sb, the B2B video campaign). over changes make_run's
        arguments: its keywords and more_campaigns are added to the fixture's, anything else (suggested, ...) replaces
        the default."""
        run = dict(queries=QUERIES, search_terms=SEARCH_TERMS, suggested=SUGGESTED, extra=SB_FILES if sb else None)
        run['more_campaigns'] = [dict(T.campaign(B2B_EXACT), siteRestrictions=['AMAZON_BUSINESS']),
                                 dict(T.campaign(B2B_STWS), siteRestrictions=['AMAZON_BUSINESS'])] + list(over.pop('more_campaigns', []))
        run['keywords'] = KEYWORDS + list(over.pop('keywords', []))
        run.update(over)
        T.make_run(self.run_dir, **run)
        product = T.product(sb_video={'campaigns': []}) if sb else T.product()
        return planner.build(T.ASIN, product, T.shared_config(), self.run_dir, 'weekly', T.TODAY, now_utc=T.NOW)

    def test_business_copy_is_never_paused_or_negated(self):      # Review Focus 1
        out = self.plan()
        self.assertFalse([x for x in T.by_type(out, 'Pause keyword') if x.get('keyword_id') == '901'])
        self.assertFalse([x for x in T.by_type(out, 'Negative exact') if x.get('campaign_id') in ('108', '109')])
        self.assertFalse([x for x in out['changes'] if x['type'] == 'New exact campaign' and x['keyword'] == 'blank cards'
                          and 'B2B' in str(x.get('source'))])
        # nor is a business keyword moved into a consumer exact campaign ('zebra cards' is a new search for consumers)
        self.assertFalse([x for x in T.by_type(out, 'New exact campaign') if 'Business' in str(x.get('source'))])

    def test_business_keyword_priced_on_b2b_conversion(self):
        out = self.plan()
        row = T.one(out, 'Bid change', keyword_id='901')
        bt = {r['term']: r for r in out['business_terms']}
        b = row['baseline_cvr']
        # the pool: 3 orders on the 77 B2B keyword clicks, shrunk by 10 clicks toward the account's B2B conversion (config)
        self.assertEqual(b, round((3 + 10 * T.CONFIG['business']['pool_prior_cvr']) / (77 + 10), 4))
        # an exact row leans on its search's business record: 3 orders on 40 B2B clicks, shrunk toward the pool. Against
        # the search's 10% market that is an index of about 0.75 on 40 clicks: a trim to 70% of that breakeven
        breakeven = 5.0 * ((3 + 10 * bt['blank cards']['cvr_est']) / (40 + 10))
        self.assertEqual(row['breakeven'], round(5.0 * (3 + 10 * bt['blank cards']['cvr_est']) / 50, 2))
        self.assertEqual((row['owner_kind'], row['family'], row['role']), ('business', 'Business', 'Trim'))
        # $1.05 to the trim is a cut of more than 50% on 3 orders: it steps down 50% this run (decision 107)
        self.assertEqual(row['new_proposed'], round(max(0.10, 0.7 * breakeven), 2))
        self.assertEqual(row['new'], round(1.05 * 0.5, 2))
        # the why names the prior actually used (the search's own business estimate, the pool beside it) and the search's
        # business role; prior_cvr carries that prior, baseline_cvr stays the pool
        prior = bt['blank cards']['cvr_est']
        self.assertEqual(row['prior_cvr'], round(prior, 4))
        self.assertEqual(row['why'], f"Amazon Business campaign: priced on the B2B campaigns' own conversion ({prior:.0%} on this "
                                     f"search, {b:.0%} pooled, 10-click prior), never on the consumer search. Its search's B2B "
                                     f"role is Trim: {bt['blank cards']['why']}.")

    def test_business_hold_says_which_breakeven(self):
        # 908's search has no SQP market, so it holds; with 3 orders, at its own breakeven
        rows = {p['keyword_id']: p for p in self.plan(keywords=[T.keyword('908', 'bulk blank cards', 'exact', B2B_EXACT, 1.05, 6, 3, 5.0)])['keyword_plan']}
        self.assertEqual(rows['908']['action'], 'Hold at breakeven (business)')
        self.assertEqual(rows['903']['action'], 'Hold at breakeven (business, capped at the B2B average until 3 orders)')

    def test_business_trim_on_its_own_index(self):
        # 'gold cards' (10% market conversion): 1 order on 20 B2B clicks, shrunk toward the pool, is an index of about 0.57.
        # Under 0.8 on 15-29 clicks: trimmed to 70% of its own breakeven, not paused (that needs 30+ clicks)
        out = self.plan(keywords=[T.keyword('906', 'gold cards', 'exact', B2B_EXACT, 1.05, 20, 1, 8.0)])
        row = T.one(out, 'Bid change', keyword_id='906')
        market = next(t for t in out['terms'] if t['term'] == 'gold cards')['market_cvr']
        index = (1 + 10 * row['baseline_cvr']) / (20 + 10) / market
        self.assertTrue(0.5 <= index < 0.8, index)
        self.assertEqual((row['owner_kind'], row['role']), ('business', 'Trim'))
        self.assertEqual(row['new'], round(max(0.10, 0.7 * row['breakeven']), 2))
        self.assertIn('Trim', next(p for p in out['keyword_plan'] if p['keyword_id'] == '906')['action'])

    def test_business_pause_on_its_own_evidence(self):
        row = T.one(self.plan(), 'Pause keyword', keyword_id='902')
        self.assertEqual(row['owner_kind'], 'business')
        self.assertIn('business', row['why'].lower())

    def test_business_row_without_market_holds(self):             # Review Focus 2: no SQP row for the phrase search
        row = T.one(self.plan(), 'Bid change', keyword_id='903')
        self.assertEqual(row['role'], 'Hold')

    def test_business_plan_rows_and_summary(self):
        out = self.plan()
        rows = {p['keyword_id']: p for p in out['keyword_plan'] if p.get('owner_kind') == 'business'}
        self.assertEqual(sorted(rows), ['901', '902', '903'])
        for p in rows.values():   # never an invest role, never the SKC's duplicate, never moved into a consumer SKC
            self.assertNotEqual(p['role'], 'Rank')
            self.assertNotIn('exact SKC', p['action'])
        # 3 orders on the 77 B2B clicks, shrunk by 10 clicks toward the account's B2B conversion (config, dated)
        prior = T.CONFIG['business']['pool_prior_cvr']
        pooled = round((3 + 10 * prior) / (77 + 10), 4)
        self.assertEqual({p['baseline_cvr'] for p in rows.values()}, {pooled})
        # no business invest search in this fixture ('zebra cards' has no B2B search-term row, so its business record is a Test)
        self.assertEqual(out['summary'][0]['business'], dict(
            campaigns=2, keywords=3, pooled_cvr=pooled, bid_changes=2, pauses=1,
            pool_prior=dict(cvr=round(prior, 4), as_of=T.CONFIG['business']['pool_prior_as_of'], source='config'),
            invest=0, prove_first=0, copies_paused=0, negatives=0, new_keywords=0, stop_loss_reviews=0, si_rows=1,
        stop_loss_step_downs=0))   # the business stop-loss step-downs the run writes itself (autonomous runs, 2026-10-22)

    def test_an_archived_business_campaign_is_not_counted(self):
        archived = dict(T.campaign(B2B_SKC), state='ARCHIVED', siteRestrictions=['AMAZON_BUSINESS'])
        self.assertEqual(self.plan(more_campaigns=[archived])['summary'][0]['business']['campaigns'], 2)

    def test_a_b2b_campaign_named_like_an_skc_never_owns_the_consumer_search(self):
        # 'blank cards' is promoted for consumers. A B2B campaign named like its exact SKC is the business owner, so the
        # consumer SKC is still created and the consumer exact (keyword 2) moves into it, never paused as that campaign's
        # copy. Both ways a name reads as an SKC: the campaign record (idle) and a keyword row in it
        b2b_skc = dict(T.campaign(B2B_SKC), siteRestrictions=['AMAZON_BUSINESS'])
        for keywords in ([], [T.keyword('905', 'blank cards', 'exact', B2B_SKC, 1.05, 6, 2, 5.0)]):
            with self.subTest(keyword_rows=len(keywords)):
                out = self.plan(more_campaigns=[b2b_skc], keywords=keywords)
                self.assertEqual(T.one(out, 'New exact campaign', keyword='blank cards')['campaign'],
                                 f'Cards - {T.ASIN} - Exact SKC - blank cards - TOS Rank')
                self.assertFalse(T.by_type(out, 'Reuse exact campaign'))
                consumer = next(p for p in out['keyword_plan'] if p['keyword_id'] == '2')
                self.assertNotIn('Pause here', consumer['action'])
                self.assertTrue(T.one(out, 'Pause keyword', keyword_id='2')['why'].startswith('Moves to its own exact campaign'))

    def test_business_pause_is_not_in_the_promotion_bundle(self):   # Review Focus 3
        # 'blank cards' is promoted; 904 is its exact twin in the B2B campaign with 40 clicks and no orders: a business pause
        # that shares the promotion's search text, which a consumer duplicate pause would be bundled by
        out = self.plan(keywords=[T.keyword('904', 'blank cards', 'exact', B2B_EXACT, 1.05, 40, 0, 20.0)])
        self.assertTrue(T.by_type(out, 'New exact campaign'))
        members, in_bundle = plan_lanes.bundles(out['changes'])
        idx = next(i for i, x in enumerate(out['changes']) if x.get('keyword_id') == '904' and x['type'] == 'Pause keyword')
        self.assertEqual(out['changes'][idx]['owner_kind'], 'business')
        self.assertNotIn(idx, in_bundle)
        # it keeps its own lane, judged on its own record, never the consumer promotion's
        self.assertNotIn('part of the promotion', out['changes'][idx]['lane_reason'])

    def test_sb_business_video_keyword_is_not_paused(self):        # Review Focus 5
        out = self.plan(sb=True)
        self.assertEqual(out['summary'][0]['sb_video']['keywords_read'], 1)
        self.assertFalse([x for x in T.by_type(out, 'SB pause keyword') if 'B2B' in x['campaign']])
        self.assertEqual(out['summary'][0]['sb_video']['video_campaigns'], 0)   # not a consumer video campaign


class BusinessVisibility(unittest.TestCase):
    def test_business_row_is_not_eligible_for_a_rescue(self):     # priced on its own numbers, not a consumer rescue
        row, data = V.fixture()
        row.update(role='Hold', family='Business')
        self.assertEqual(V.review(row, data)['reason_code'], 'role_not_eligible_for_rescue')


if __name__ == '__main__':
    unittest.main()
