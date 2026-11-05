import copy
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import plan as planner
import preview


SKILL = pathlib.Path(__file__).resolve().parents[1]
SHARED = json.loads((SKILL / 'config.json').read_text(encoding='utf-8'))
# written before the suggested mid (decision 177): its Hold keywords keep their breakeven here (test_mid_bid.py tests it)
SHARED['mid_bid'] = dict(SHARED.get('mid_bid') or {}, enabled=False)
ASIN = 'B0SAMP0005'
TODAY = '2026-10-19'
# a shadow product (its own Auto off): these tests were written when config.json had Auto off for everyone; since
# 2026-10-22 it is on, and an enabled product without price_change.json and inventory_cover.json is stale (every row held)
PRODUCT = dict(asin=ASIN, product='Glitter cards', sku='test-sku', campaign_prefix=f'{ASIN} - ', profit_per_unit=3.04,
               auto={'enabled': False})


def keyword(keyword_id='123', term='thank you cards', match='exact'):
    return dict(ASIN=ASIN, KeywordId=keyword_id, Keyword=term, MatchType=match, CampaignId='456', AdGroupId='789',
                CampaignName=f'{ASIN} - Exact SKC - {term} - TOS Rank', Clicks=100, Orders=20, Spend=20, Sales=100, Bid=.16)


def inventory(keyword_id='123', term='thank you cards', match='exact'):
    return dict(asin=ASIN, keyword_id=keyword_id, keyword=term, match=match, campaign_id='456', ad_group_id='789',
                observed_on=TODAY, strategy='down_only', current_bid=.16, effective_bid_multiplier=1,
                gates={field: True for field in ('campaign_enabled', 'ad_group_enabled', 'target_enabled', 'ad_eligible',
                       'in_stock', 'featured_offer', 'budget_available', 'schedule_open', 'negatives_clear', 'routing_clear', 'ownership_clear')},
                demand=dict(known=True, available=True, source='SQP', as_of=TODAY))


def inputs(orders=20, benchmark=True):
    query = dict(Query='thank you cards', AsinClicks=100, AsinPurchase=orders, TotalClicks=1000,
                 TotalPurchase=100, QueryVolume=3000, AsinImpressions=100, TotalImpressions=10000)
    queries = {'thank you cards': query} if benchmark else {'different query': dict(query, Query='different query')}
    metric = dict(ASIN=ASIN, SearchTerm='thank you cards', Clicks=100, Orders=orders, Spend=20, Sales=100,
                  CampaignName=f'{ASIN} - Exact SKC - thank you cards - TOS Rank', CampaignId='456', AdGroupId='789')
    target = keyword()
    target['Orders'] = orders
    campaigns = [dict(campaignId='456', name=target['CampaignName'], state='ENABLED', budget={'budget': 10})]
    # the eighth value is the SQP's data_through date, which load_inputs returns for the lanes' freshness check (auto-apply)
    return queries, [metric], [target], {'thank you cards': [.73, 1.02, 1.32]}, campaigns, [], {}, TODAY


def build(data=None, snapshot=None, shared=None):
    with tempfile.TemporaryDirectory() as directory:
        if snapshot is not None:
            pathlib.Path(directory, 'visibility_inputs.json').write_text(json.dumps(snapshot), encoding='utf-8')
        with mock.patch.object(planner, 'load_inputs', return_value=data or inputs()):
            return planner.build(ASIN, PRODUCT, shared or SHARED, directory, 'weekly', TODAY)


class VisibilityIntegrationTests(unittest.TestCase):
    def test_existing_idx_thresholds_and_roles_remain(self):
        for orders, expected in ((20, 'Rank'), (10, 'Hold'), (5, 'Trim')):
            with self.subTest(orders=orders):
                output = build(inputs(orders))
                term = next(row for row in output['terms'] if row['term'] == 'thank you cards')
                self.assertEqual(term['role'], expected)
                self.assertIsNotNone(term['index'])
        self.assertEqual(SHARED['thresholds']['index_invest'], 1.1)
        self.assertEqual(SHARED['thresholds']['index_hold'], .8)

    def test_exact_idx_boundaries_are_not_display_rounding(self):
        self.assertTrue(planner.at_least(.11 / .1, 1.1))
        self.assertTrue(planner.at_least(.08 / .1, .8))
        self.assertFalse(planner.at_least(1.0999, 1.1))
        self.assertFalse(planner.at_least(.7999, .8))

    def test_missing_market_does_not_invent_idx_or_trim(self):
        output = build(inputs(orders=5, benchmark=False))
        term = next(row for row in output['terms'] if row['term'] == 'thank you cards')
        self.assertIsNone(term['index'])
        self.assertEqual(term['role'], 'Test')
        self.assertEqual(term['index_status'], 'unknown_market_benchmark')

    def test_zero_market_purchases_are_observed_not_missing(self):
        data = inputs()
        data[0]['thank you cards']['TotalPurchase'] = 0
        output = build(data)
        term = output['terms'][0]
        self.assertIsNotNone(term['market_cvr'])

    def test_zero_activity_inventory_is_included(self):
        snapshot = dict(asin=ASIN, inventory_complete=True, inventory=[inventory('222', 'assorted thanks')])
        output = build(snapshot=snapshot)
        target = next(row for row in output['keyword_plan'] if row['keyword_id'] == '222')
        self.assertEqual(target['clicks90'], 0)
        self.assertTrue(target['inventory_only'])
        self.assertTrue(any(row['keyword_id'] == '222' for row in output['visibility_review']['rows']))

    def test_paused_inventory_does_not_generate_bid_change(self):
        item = inventory()
        item['gates']['target_enabled'] = False
        output = build(snapshot=dict(asin=ASIN, inventory_complete=True, inventory=[item]))
        self.assertTrue(output['keyword_plan'][0]['action'].startswith('Keep'))
        self.assertFalse(any(row['type'] == 'Bid change' and row.get('keyword_id') == '123' for row in output['changes']))

    def test_inventory_identity_collision_fails_closed(self):
        item = inventory()
        item['match'] = 'broad'
        with self.assertRaisesRegex(ValueError, 'identity differs'):
            planner.merge_keyword_inventory([keyword()], dict(inventory=[item]), ASIN, TODAY, SHARED['visibility'])

    def test_conflicting_report_duplicates_fail_closed(self):
        original = keyword()
        changed = dict(original, Orders=99)
        with self.assertRaisesRegex(ValueError, 'Conflicting keyword report'):
            planner.merge_keyword_inventory([original, changed], {}, ASIN, TODAY, SHARED['visibility'])
        self.assertEqual(len(planner.merge_keyword_inventory([original, original], {}, ASIN, TODAY, SHARED['visibility'])), 1)

    def test_inventory_only_exact_owner_is_not_its_own_duplicate(self):
        data = inputs()
        data[2][0] = keyword('999', 'some other keyword')
        item = inventory()
        output = build(data, dict(asin=ASIN, inventory_complete=True, inventory=[item]))
        target = next(row for row in output['keyword_plan'] if row['keyword_id'] == '123')
        self.assertEqual(target['family'], 'SKC')
        self.assertFalse(any(row['type'] == 'Pause keyword' and row.get('keyword_id') == '123' for row in output['changes']))
        self.assertFalse(any(row['type'] == 'Reuse exact campaign' and row.get('campaign_id') == '456' for row in output['changes']))

    def test_blocked_owner_defers_dependent_routing(self):
        data = inputs()
        duplicate = keyword('222')
        duplicate.update(CampaignId='654', AdGroupId='987', CampaignName=f'{ASIN} - discovery exact')
        data[2].append(duplicate)
        data[1].append(dict(data[1][0], CampaignId='654', AdGroupId='987', CampaignName=duplicate['CampaignName']))
        owner = inventory()
        owner['gates']['ad_eligible'] = False
        duplicate_inventory = dict(inventory('222'), campaign_id='654', ad_group_id='987')
        duplicate_inventory['gates']['routing_clear'] = False
        output = build(data, dict(asin=ASIN, inventory_complete=True, inventory=[owner, duplicate_inventory]))
        self.assertFalse(any(row['type'] in ('Pause keyword', 'Negative exact', 'New exact campaign', 'Reuse exact campaign')
                             and row.get('keyword') == 'thank you cards' for row in output['changes']))

    def test_retained_rank_missing_from_old_inventory_is_not_recreated(self):
        data = inputs()
        data[2][0] = keyword('999', 'different keyword')
        with mock.patch.dict(PRODUCT, {'invest_log': {'thank you cards': {'since': TODAY}}}):
            output = build(data)
        self.assertIn('thank you cards', output['visibility_review']['retained_rank_searches'])
        self.assertFalse(any(row['type'] in ('New exact campaign', 'Reuse exact campaign') and row.get('keyword') == 'thank you cards'
                             for row in output['changes']))
        self.assertEqual(output['summary'][0]['rank_reviews_deferred'], 1)

    def test_wrong_asin_snapshot_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, 'visibility_inputs.json').write_text(json.dumps(dict(asin='OTHER')), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'this ASIN'):
                planner.load_visibility_inputs(directory, ASIN)

    def test_guarded_test_does_not_get_baseline_bid_payload(self):
        with mock.patch.object(planner.visibility, 'build_review', return_value=dict(rows=[dict(keyword_id='123',
                               guard_bid_change=True, reason='Finite test needs review')], counts={}, missing_requests=[])):
            output = build(inputs(orders=5, benchmark=False))
        self.assertEqual(output['keyword_plan'][0]['new_bid'], .16)
        self.assertFalse(any(row['type'] == 'Bid change' and row.get('keyword_id') == '123' for row in output['changes']))

    def test_contextual_broad_recommendation_is_retained(self):
        data = inputs()
        data[2][0]['MatchType'] = 'broad'
        item = inventory(match='broad')
        recommendation = dict(item, fetched_on=TODAY, low=.73, median=1.02, high=1.32, source='MAP')
        snapshot = dict(asin=ASIN, inventory_complete=True, inventory=[item], recommendations=[recommendation])
        output = build(data, snapshot)
        self.assertEqual(output['keyword_plan'][0]['suggested'], (.73, 1.02, 1.32))
        self.assertEqual(output['keyword_plan'][0]['recommendation_source'], 'contextual')

    def test_experiment_cannot_accidentally_become_apply_payload(self):
        for change in (dict(visibility_experiment=True), dict(type='Visibility experiment')):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, 'preview-only'):
                    planner.write_outputs(directory, dict(changes=[change]), SHARED, ASIN)
                self.assertFalse(pathlib.Path(directory, 'payloads').exists())

    def test_rerun_archives_stale_generated_payloads(self):
        # Merged with the auto-apply lanes: payloads are written by lane folder, so the earlier plan's files are archived
        # from there, with their folder; a top-level payload left by a run planned before the lanes is archived too. The
        # manifest names files by their path under payloads/. The fixture's raise is short of proof, so it is held
        # (payloads/held/; a person's call until decision 107, 2026-10-23): it goes past breakeven on the Hold uplift, which
        # is switched on here (off in config.json since decision 135, when a raise to breakeven alone applies on its own)
        shared = copy.deepcopy(SHARED)
        shared['hold_uplift'] = dict(shared['hold_uplift'], enabled=True)
        shared['thresholds'] = dict(shared['thresholds'], non_rank_bid_factor=1)   # the uplift is on breakeven (decision 139 off)
        output = build(inputs(10), shared=shared)
        with tempfile.TemporaryDirectory() as directory:
            planner.write_outputs(directory, output, SHARED, ASIN)
            old_payload = pathlib.Path(directory, 'payloads', 'held', '4_bids_01.json')
            self.assertTrue(old_payload.exists())
            manifest = json.loads(pathlib.Path(directory, 'payload_manifest.json').read_text())
            self.assertEqual(manifest['files'], [])
            self.assertEqual([row['file'] for row in manifest['held_files']], ['held/4_bids_01.json'])
            legacy = pathlib.Path(directory, 'payloads', '4_bids_01.json')
            legacy.write_text('[]', encoding='utf-8')
            empty = copy.deepcopy(output)
            empty['changes'] = []
            planner.write_outputs(directory, empty, SHARED, ASIN)
            self.assertFalse(old_payload.exists())
            self.assertFalse(legacy.exists())
            archive = pathlib.Path(directory, 'payload_archive')
            self.assertEqual(len(list(archive.glob('*/held/4_bids_01.json'))), 1)
            self.assertEqual(len(list(archive.glob('*/held/rows.json'))), 1)
            self.assertEqual(len(list(archive.glob('*/4_bids_01.json'))), 1)
            manifest = json.loads(pathlib.Path(directory, 'payload_manifest.json').read_text())
            self.assertEqual(manifest['files'], [])

    def test_preview_escapes_data_and_labels_proposals(self):
        review = dict(counts={'under_delivering': 1}, rows=[dict(keyword='<script>bad</script>', match='broad', role='Discovery',
                      reason='Test, not execution', proposal=dict(candidate_bid=.73, needs_boundaries=True))])
        rendered = preview.visibility_review_html([('Cards', review)])
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>bad', rendered)
        self.assertIn('not applied bids', rendered)


if __name__ == '__main__':
    unittest.main()
