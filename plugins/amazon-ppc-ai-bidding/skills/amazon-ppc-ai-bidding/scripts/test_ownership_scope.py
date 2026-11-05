"""Mixed-ASIN ownership exclusions cannot escape through Auto, approval, SI or stale payload paths."""
import os
import glob
import unittest

import tempfile

import ownership_scope as scope
import plan
import plan_lanes
import test_dashboard_approvals as D
import test_plan_lanes as T


def ownership(**over):
    return dict(dict(mode='exclusive_campaigns', asin=T.ASIN, approved_by='Kim', approved_on='2026-10-23',
                     excluded_campaign_ids=['105'], excluded_ad_group_ids=['205']), **over)


def product():
    return dict(asin=T.ASIN, ownership_scope=ownership())


class ScopeRowsTest(unittest.TestCase):
    def test_actual_target_only_payload_must_resolve_to_allowed_plan_owner(self):
        changes = [dict(type='Bid change', campaign_id='106', keyword_id='66'),
                   dict(type='Bid change', campaign_id='105', keyword_id='55')]
        self.assertIsNone(scope.payload_reason([dict(type='sp_keywords', keywordId='66', bid=0.5)], product(), changes))
        for kid in ('55', '99'):
            self.assertIsNotNone(scope.payload_reason([dict(type='sp_keywords', keywordId=kid, bid=0.5)], product(), changes))

    def test_actual_payload_cannot_substitute_parent_ids_or_asins(self):
        changes = [dict(type='Negative exact', campaign_id='106', ad_group_id='206')]
        for row in (dict(campaignId='105', adGroupId='206'), dict(campaignId='999', adGroupId='206'),
                    dict(campaignId='106', adGroupId='999'), dict(campaignId='106', asin='OTHER'),
                    dict(campaignId='106', product_ad=dict(sku='OTHER-SKU'))):
            self.assertIsNotNone(scope.payload_reason([row], product(), changes))

    def test_raw_new_build_placeholders_require_matching_planned_creation(self):
        change = dict(type='New SB video campaign', campaign='new same-ASIN video', asin=T.ASIN)
        row = dict(campaign=dict(name=change['campaign']), ad_group=dict(campaignId='<campaignId>'),
                   ad=dict(adGroupId='<adGroupId>', creative=dict(asins=[T.ASIN])))
        self.assertIsNone(scope.payload_reason([row], product(), [change]))
        row['campaign']['name'] = 'unplanned video'
        self.assertIsNotNone(scope.payload_reason([row], product(), [change]))

    def test_shared_targets_pauses_placements_and_funnels_are_all_blocked(self):
        for typ in ('Target bid', 'Target pause', 'SB pause keyword', 'Pause keyword', 'Bid change',
                    'Budget and top of search', 'Budget step', 'Negative exact', 'Business invest', 'New exact keyword'):
            with self.subTest(type=typ):
                self.assertIn('solely SI-managed', scope.reason(dict(type=typ, campaign_id='105'), product()))

    def test_exclusive_existing_campaign_allowed_and_group_exclusion_also_enforced(self):
        row = dict(type='SB pause keyword', campaign_id='106', ad_group_id='206')
        self.assertIsNone(scope.reason(row, product()))
        row['ad_group_id'] = '205'
        self.assertIsNotNone(scope.reason(row, product()))

    def test_missing_or_placeholder_campaign_id_fails_closed(self):
        for cid in (None, '', '<campaignId>', 'campaign-name', False):
            self.assertIsNotNone(scope.reason(dict(type='Bid change', campaign_id=cid, keyword_id='99'), product()))

    def test_only_explicit_same_asin_new_campaign_allowed(self):
        for typ in scope.NEW_CAMPAIGNS:
            row = dict(type=typ)
            self.assertIsNotNone(scope.reason(row, product()))
            row['asin'] = T.ASIN
            self.assertIsNone(scope.reason(row, product()))
            row['creative'] = dict(asins=[T.ASIN, 'B0OTHER001'])
            self.assertIsNotNone(scope.reason(row, product()))

    def test_placeholders_require_same_asin_new_parent_in_this_plan(self):
        parent = dict(type='New exact campaign', asin=T.ASIN, row_id='new')
        child = dict(type='Negative exact', asin=T.ASIN, campaign_id='<campaignId>',
                     ad_group_id='<adGroupId>', new_campaign_row_id='new')
        self.assertIsNotNone(scope.reason(child, product()))
        self.assertIsNone(scope.reason(child, product(), [parent, child]))
        child['keyword_id'] = '88'  # cannot disguise an existing target as a new child
        self.assertIsNotNone(scope.reason(child, product(), [parent, child]))

    def test_broad_si_is_held_and_exact_exclusive_entities_are_allowed(self):
        row = dict(type='Scale Insights rules', asin=T.ASIN)
        self.assertIsNotNone(scope.reason(row, product()))
        row['scope_entities'] = [dict(campaign_id='106', ad_group_id='206')]
        self.assertIsNone(scope.reason(row, product()))
        row['scope_entities'].append(dict(campaign_id='105', ad_group_id='205'))
        self.assertIsNotNone(scope.reason(row, product()))

    def test_product_lists_need_unaffected_shared_consumer_proof(self):
        row = dict(type='Scale Insights setup', keyword='blacklist rescue',
                   scope_entities=[dict(campaign_id='106', ad_group_id='206')])
        self.assertIsNotNone(scope.reason(row, product()))
        row.update(shared_product_lists_unaffected=True, scope_evidence='verified-list-consumers.json')
        self.assertIsNone(scope.reason(row, product()))

    def test_si_checklist_preserves_exact_scope_and_product_list_proof(self):
        row = dict(type='Scale Insights setup', row_id='si', asin=T.ASIN, keyword='blacklist rescue',
                   scope_entities=[dict(campaign_id='106', ad_group_id='206')],
                   shared_product_lists_unaffected=True, scope_evidence='list-consumers.json')
        self.assertEqual(plan.scale_insights_steps([row]), [row])

    def test_unscoped_products_unchanged_but_malformed_scope_is_held(self):
        self.assertIsNone(scope.reason(dict(type='Bid change'), dict(asin=T.ASIN)))
        for bad in (None, {}, dict(ownership(), asin='OTHER'), dict(ownership(), excluded_campaign_ids='105')):
            self.assertIsNotNone(scope.reason(dict(type='Bid change', campaign_id='106'),
                                              dict(asin=T.ASIN, ownership_scope=bad)))


class ScopeLanesTest(unittest.TestCase):
    def test_held_raise_uses_none_of_the_runs_automatic_raises(self):
        # Codex review, 2026-10-23: the top raise (Bid change:1, campaign 105) is excluded, so the one automatic raise
        # the run allows goes to the next raise in an exclusive campaign, not to the held row
        with tempfile.TemporaryDirectory() as tmp:
            run = os.path.join(tmp, 'run')
            T.make_run(run)
            cfg = T.product(auto=dict(T.AUTO, max_raises=1), ownership_scope=ownership())
            out = plan.build(T.ASIN, cfg, T.shared_config(), run, 'weekly', T.TODAY, now_utc=T.NOW)
        rows = {x['row_id']: x for x in out['changes']}
        held = rows['Bid change:1']
        self.assertEqual(held['lane'], 'monitor')
        self.assertIn('solely SI-managed', held['ownership_scope_blocked'])
        self.assertEqual(rows['Bid change:4']['lane'], 'auto')
        self.assertEqual([x['row_id'] for x in out['changes'] if plan_lanes.is_raise(x) and x['lane'] == 'auto'],
                         ['Bid change:4'])
        self.assertIn('used up its 1 automatic raise', rows['Target bid change:302']['lane_reason'])


class ScopeIntegrationTest(D.Base):
    def test_raw_bid_payload_tampering_is_rejected_even_when_plan_is_safe(self):
        self.plan_run(shadow=False, ownership_scope=ownership())
        filename = glob.glob(os.path.join(self.run_dir, 'payloads', 'auto', '4_bids_*.json'))[0]
        payload = D.read_json(filename)
        payload[0]['keywordId'] = '999999999'
        D.write_json(filename, payload)
        with self.assertRaisesRegex(SystemExit, 'actual payload keyword 999999999'):
            self.run_applied('auto', dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))

    def test_fresh_scoped_payloads_pass_actual_file_validation(self):
        self.plan_run(shadow=False, ownership_scope=ownership())
        out = self.run_applied('auto', dry_run=True)
        self.assertTrue(out['dry_run'])

    def test_planner_new_campaign_rows_already_carry_requested_asin(self):
        p = self.plan_run()
        creations = [c for c in p['changes'] if c['type'] in scope.NEW_CAMPAIGNS]
        self.assertTrue(creations)
        self.assertTrue(all(c.get('asin') == T.ASIN for c in creations))

    def test_harvest_default_bid_carries_campaign_id_for_scope_check(self):
        p = self.plan_run(harvest=dict(campaign_id='106', ad_group_id='206', default_bid=0.01))
        harvest = next(c for c in p['changes'] if c['type'] == 'Harvest default bid')
        self.assertEqual(harvest['campaign_id'], '106')
        self.assertIsNone(scope.reason(harvest, product()))

    def test_excluded_funnel_holds_whole_promotion_bundle(self):
        p = self.plan_run(shadow=False, ownership_scope=ownership(excluded_campaign_ids=['101'],
                                                                  excluded_ad_group_ids=['201']))
        for rid in D.BUNDLE:
            row = next(c for c in p['changes'] if c['row_id'] == rid)
            self.assertEqual(row['lane'], 'monitor')
            self.assertIn('ownership scope', row['ownership_scope_blocked'])

    def test_planner_holds_excluded_row_and_omits_it_from_executable_payloads(self):
        plan = self.plan_run(shadow=False, ownership_scope=ownership())
        row = next(c for c in plan['changes'] if c['row_id'] == 'Bid change:1')
        self.assertEqual((row['lane'], row['lane_unlocked']), ('monitor', 'monitor'))
        self.assertIn('ownership scope', row['ownership_scope_blocked'])
        for folder in ('auto', 'review'):
            filename = os.path.join(self.run_dir, 'payloads', folder, 'rows.json')
            rows = D.read_json(filename) if os.path.exists(filename) else {}
            self.assertNotIn('Bid change:1', [rid for ids in rows.values() for rid in ids])

    def test_stale_plan_cannot_be_approved_after_scope_changes(self):
        self.plan_run()
        self.edit_product(ownership_scope=ownership())
        out = self.run_cmd([D.dec('Bid change:1', 'approve')])
        self.assertEqual(out['approved'], 0)
        self.assertIn('solely SI-managed', out['skipped'][0]['reason'])

    def test_stale_payload_preflight_refuses_scope_even_with_record_anyway(self):
        self.plan_run()
        self.edit_product(ownership_scope=ownership())
        before = self.raw_product()
        for anyway in (False, True):
            with self.assertRaisesRegex(SystemExit, 'Ownership scope refuses'):
                self.run_applied('review', rows=['Bid change:1'], dry_run=True, record_anyway=anyway)
        self.assertEqual(self.raw_product(), before)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))

    def test_stale_existing_write_missing_campaign_id_is_refused(self):
        plan = self.plan_run()
        next(c for c in plan['changes'] if c['row_id'] == 'Bid change:1')['campaign_id'] = None
        D.write_json(os.path.join(self.run_dir, 'plan.json'), plan)
        self.edit_product(ownership_scope=ownership(excluded_campaign_ids=['999'], excluded_ad_group_ids=['998']))
        with self.assertRaisesRegex(SystemExit, 'exact campaign ID'):
            self.run_applied('review', rows=['Bid change:1'], dry_run=True)

    def test_record_anyway_preserves_historical_truth_with_scope_warning(self):
        self.plan_run()
        self.edit_product(ownership_scope=ownership())
        out = self.run_applied('review', rows=['Bid change:1'], record_anyway=True)
        self.assertTrue(any('historical truth only' in w for w in out['warnings']))
        self.assertIn('Bid change:1', D.read_json(os.path.join(self.run_dir, 'payloads', 'applied_rows.json')))


if __name__ == '__main__':
    unittest.main()
